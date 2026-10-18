"""Panel de estado: qué hay, qué falta y qué toca hacer este mes, sin correr nada pesado."""
from __future__ import annotations

import datetime as dt
import gzip
import json
from pathlib import Path

from . import config, publicar
from .version import VERSION

_cache: dict = {}
_cache_pub: dict = {"t": 0.0, "v": None}


def _fecha(p: Path) -> str | None:
    return dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if p.exists() else None


def _por_mtime(clave: str, p: Path, calcular):
    if not p.exists():
        return None
    m = p.stat().st_mtime
    if clave not in _cache or _cache[clave][0] != m:
        try:
            _cache[clave] = (m, calcular(p))
        except Exception as e:  # noqa: BLE001 - un archivo dañado no debe tumbar el panel
            _cache[clave] = (m, {"error": str(e)[:120]})
    return _cache[clave][1]


def _ultimo_mes_satelite(p: Path) -> str:
    ultimo = 0
    with gzip.open(p, "rt", encoding="utf-8") as f:
        cab = f.readline().strip().split(",")
        ia, im = cab.index("anio"), cab.index("mes")
        for linea in f:
            c = linea.split(",", max(ia, im) + 1)
            try:
                ultimo = max(ultimo, int(float(c[ia])) * 12 + int(float(c[im])) - 1)
            except (ValueError, IndexError):
                continue
    return f"{ultimo // 12}-{ultimo % 12 + 1:02d}"


def _cosechas(p: Path) -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    ult = {"riopaila": None, "castilla": None}
    n = 0
    for r in wb.worksheets[0].iter_rows(min_row=2, values_only=True):
        if not r or not r[0] or r[2] is None:
            continue
        f = r[2].date() if hasattr(r[2], "date") else None
        if f is None:
            continue
        n += 1
        planta = "riopaila" if str(r[0]).strip().startswith("3") else "castilla"
        if ult[planta] is None or f > ult[planta]:
            ult[planta] = f
    wb.close()
    return {"filas": n, **{k: v.isoformat() if v else None for k, v in ult.items()}}


def _corrida(p: Path) -> dict:
    meta = json.loads(p.read_text(encoding="utf-8"))
    d = p.parent
    est = json.loads((d / "estimados.json").read_text(encoding="utf-8")) if (d / "estimados.json").exists() else []
    fac = json.loads((d / "factores.json").read_text(encoding="utf-8")) if (d / "factores.json").exists() else {}
    por = {}
    for e in est:
        x = por.setdefault(e["planta"], {"suertes": 0, "toneladas": 0.0, "area": 0.0})
        x["suertes"] += 1
        x["toneladas"] += e.get("ton_estimadas") or 0
        x["area"] += e.get("area_ha") or 0
    for x in por.values():
        x["tch"] = round(x["toneladas"] / x["area"], 1) if x["area"] else None
        x["toneladas"] = round(x["toneladas"])
    return {"fecha": meta.get("fecha_corrida"), "version": meta.get("modelo_version"),
            "satelite": meta.get("satelite_hasta"), "cosechas_hasta": meta.get("cosechas_hasta"),
            "plantas": por, "factores": {k: v.get("factor") for k, v in fac.items()},
            "historial": sorted(x.stem.split("_", 1)[1] for x in (d / "historial").glob("estimados_*.json"))[-6:]}


def mes_satelite_disponible(hoy: dt.date) -> str:
    """El último mes con imágenes suficientes: el actual desde el día 20, si no el anterior (como el motor)."""
    t = hoy.year * 12 + hoy.month - 1 - (0 if hoy.day >= 20 else 1)
    return f"{t // 12}-{t % 12 + 1:02d}"


def calcular(con_publicado: bool = True) -> dict:
    import time

    cfg = config.cargar()
    k = config.llaves()
    hoy = dt.date.today()
    ins = Path(cfg["carpeta_insumos"])
    archivos = [
        ("ZQM histórico", ins / "02 Cosecha y molienda" / "historico zqm.xlsx", True),
        ("ZQM del año", ins / "02 Cosecha y molienda" / "zqm 26.xlsx", True),
        ("Cosechas recientes", ins / "02 Cosecha y molienda" / "cosechas_recientes.xlsx", True),
        ("Base de aforos", ins / "01 Estimados y TCH" / "Base de aforos completa 2026.xlsx", True),
    ]
    insumos = [{"nombre": n, "ruta": str(p), "existe": p.exists(), "modificado": _fecha(p), "obligatorio": o}
               for n, p, o in archivos]
    sat = {pl: _por_mtime(f"sat_{pl}", config.satelite(cfg) / f"mensual_{pl}.csv.gz", _ultimo_mes_satelite)
           for pl in ("riopaila", "castilla")}
    cos = _por_mtime("cosechas", archivos[2][1], _cosechas)
    cor = _por_mtime("corrida", config.tablero_data(cfg) / "meta.json", _corrida)
    pub = None
    if con_publicado and cfg.get("alias"):
        if time.time() - _cache_pub["t"] > 60:
            _cache_pub.update(t=time.time(), v=publicar.publicado(cfg))
        pub = _cache_pub["v"]

    avisos = []
    falta_cfg = [n for n, ok in (("carpeta de insumos", ins.exists()), ("carpeta de trabajo", config.trabajo(cfg).exists()),
                                 ("llave de Earth Engine", k.get("gee_llave_json"))) if not ok]
    if falta_cfg:
        avisos.append({"nivel": "atencion", "texto": "Falta configurar: " + ", ".join(falta_cfg) + ".", "ir": "configuracion"})
    for i in insumos:
        if i["obligatorio"] and not i["existe"]:
            avisos.append({"nivel": "atencion", "texto": f"No encuentro «{i['nombre']}» en la carpeta de insumos.",
                           "ir": "configuracion"})
    if cos and not cos.get("error"):
        for pl, nombre in (("riopaila", "Riopaila"), ("castilla", "Castilla")):
            f = cos.get(pl)
            if f and (hoy - dt.date.fromisoformat(f)).days > 10:
                avisos.append({"nivel": "info", "texto": f"Las cosechas de {nombre} cargadas llegan hasta el "
                               f"{dt.date.fromisoformat(f):%d-%m}. Carga las del mes antes de correr el motor."})
    disp = mes_satelite_disponible(hoy)
    if all(sat.get(pl) and isinstance(sat[pl], str) for pl in sat) and min(sat.values()) < disp:
        avisos.append({"nivel": "info", "texto": f"Hay imágenes del satélite de {disp} que la tabla todavía no tiene: "
                       "corre el motor con el satélite."})
    if cor and not cor.get("error"):
        if cor["fecha"] and cor["fecha"][:7] < hoy.strftime("%Y-%m") and hoy.day >= 2:
            avisos.append({"nivel": "atencion", "texto": f"La última corrida es del {cor['fecha']}: toca la de este mes."})
        if pub and pub.get("ok") and pub.get("fecha") != cor["fecha"]:
            avisos.append({"nivel": "info", "texto": f"La corrida del {cor['fecha']} no se ha publicado: el tablero "
                           f"muestra la del {pub.get('fecha')}."})
    elif config.trabajo(cfg).exists():
        avisos.append({"nivel": "atencion", "texto": "Todavía no hay ninguna corrida en la carpeta de trabajo."})
    if not avisos:
        avisos.append({"nivel": "ok", "texto": "Todo al día."})
    return {"version": VERSION, "hoy": hoy.isoformat(), "insumos": insumos, "satelite": sat, "satelite_disponible": disp,
            "cosechas": cos, "corrida": cor, "publicado": pub, "avisos": avisos,
            "configurado": not falta_cfg, "trabajo": str(config.trabajo(cfg))}
