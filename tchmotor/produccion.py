# -*- coding: utf-8 -*-
"""Corrida mensual del estimador sin base de datos.

Entradas (todas locales): ZQM histórico y 2026 (Excel), maestros de suertes (JSON de Rio Map),
base de aforos (Excel, para el aforo sintético) y la tabla mensual de Earth Engine.
Salidas: archivos JSON que lee el tablero estático (estimados, reales, factores, curvas, meta).

El modelo se entrena con las campañas COMPLETAS anteriores a la vigente (así se validó) y el
factor de la campaña sale de las cosechas ya cerradas en ella: corrige el corrimiento del año
que la historia no enseña (2026: Castilla MAPE 14,2→11,2, Riopaila 10,5→9,4).
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import dataset_gee as dg
from .curva import limpiar_nube
from .modelo import MotorTCH

VERSION = "ee-1.0"
QUITAR = ("clima", "tipo")  # calor y tipo de cosecha no mejoran fuera de muestra (27-sep-2026)
RECAL_MIN = 15
EDAD_MIN = 4  # antes de 4 meses la curva no alcanza para estimar
_DIAS = 30.44


def _t(d: date) -> int:
    return d.year * 12 + d.month - 1


def _fecha(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def mes_vigente(hoy: date) -> int:
    """Último mes con satélite suficiente: el actual desde el día 20, si no el anterior."""
    return _t(hoy) if hoy.day >= 20 else _t(hoy) - 1


def cargar_maestros(carpeta=dg.MAESTROS) -> dict:
    out = {}
    for fn, planta in (("maestro_suertes.json", "riopaila"), ("maestro_castilla.json", "castilla")):
        for sec, v in json.load(open(Path(carpeta) / fn, encoding="utf-8")).items():
            out[sec] = {**v, "planta": planta}
    return out


COSECHAS_RECIENTES = Path.home() / "Documents" / "cosechas_recientes.xlsx"


def _fecha_libre(x):
    """Fecha de Excel: datetime, 'AAAA-MM-DD' o 'D/MM/AAAA'."""
    if hasattr(x, "year"):
        return date(x.year, x.month, x.day)
    s = str(x or "").strip()[:10]
    try:
        if "/" in s:
            d, m, a = s.split("/")
            return date(int(a), int(m), int(d))
        return date.fromisoformat(s)
    except Exception:
        return None


def leer_cosechas_recientes(ruta=COSECHAS_RECIENTES) -> pd.DataFrame:
    """Hoja 1 del Excel de cosechas que aún no trae el ZQM: suerte, TCH real, fecha en que terminó."""
    import openpyxl

    if not Path(ruta).exists():
        return pd.DataFrame(columns=["sec_ste", "tch", "fecha"])
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    filas = list(wb.worksheets[0].iter_rows(values_only=True))
    wb.close()
    hdr = [str(h or "").strip().lower() for h in filas[0]]

    def col(*claves):
        return next(i for i, h in enumerate(hdr) if any(k in h for k in claves))

    cs, ct, cf = col("ubicaci", "sec", "suerte"), col("tch"), col("fecha")
    out = [{"sec_ste": str(r[cs]).strip(), "tch": pd.to_numeric(r[ct], errors="coerce"), "fecha": _fecha_libre(r[cf])}
           for r in filas[1:] if r and r[cs]]
    return pd.DataFrame(out)


def cosechas_recientes(tabla: pd.DataFrame, maestro: dict, ciclos: pd.DataFrame):
    """Convierte las cosechas del complemento al formato de `cortes_zqm`.

    - Si el ZQM ya trae esa cosecha (misma suerte, ±45 días) manda el ZQM y la fila se omite.
    - Inicio del ciclo cosechado: la fecha más reciente entre la cosecha anterior del ZQM, el último
      corte del maestro (si todavía no registra esta cosecha) y la siembra, con al menos 6 meses.
    - Soca: la que el maestro marca creciendo; si el maestro ya registró esta cosecha, esa menos 1.
    Devuelve (ciclos nuevos, motivos de descarte).
    """
    previas = {s: sorted(date.fromisoformat(h) for h in g) for s, g in ciclos.groupby("sec_ste").harvest}
    filas, fuera = [], Counter()
    for r in tabla.itertuples(index=False):
        v, f = maestro.get(r.sec_ste), r.fecha
        if v is None:
            fuera["no está en el maestro"] += 1
            continue
        if f is None or r.tch != r.tch or not 30 <= r.tch <= 250:
            fuera["sin fecha o TCH fuera de rango"] += 1
            continue
        zqm = previas.get(r.sec_ste, [])
        if any(abs((h - f).days) <= 45 for h in zqm):
            fuera["ya está en el ZQM"] += 1
            continue
        m_ult = _fecha(v.get("fecha_ultimo_corte"))
        ya_registrada = m_ult is not None and abs((m_ult - f).days) <= 20
        candidatas = [h for h in zqm if h < f] + [_fecha(v.get("fecha_siembra"))]
        if m_ult is not None and not ya_registrada:
            candidatas.append(m_ult)
        candidatas = [d for d in candidatas if d is not None and (f - d).days >= 180]
        if not candidatas:
            fuera["sin corte anterior"] += 1
            continue
        cut = max(candidatas)
        edad = (f - cut).days / _DIAS
        if not 8 <= edad <= 24:
            fuera["edad fuera de 8-24 meses"] += 1
            continue
        soca = v.get("numero_corte")
        soca = None if soca is None else int(soca) - (1 if ya_registrada else 0)
        t_cos = _t(f)
        filas.append({
            "sec_ste": r.sec_ste, "planta": v["planta"], "anio": f.year, "mes": f.month,
            "corte": float(soca) if soca is not None else np.nan, "variedad": v.get("variedad"),
            "ha": v.get("area_neta_ha"), "edad": edad, "tch": float(r.tch), "tipo_cosecha": None,
            "t_cos": t_cos, "t_cut": t_cos - int(round(edad)), "harvest": f.isoformat(), "cut": cut.isoformat(),
            "key": f"{r.sec_ste}|{f.year}|{f.month}|{soca}",
        })
    return pd.DataFrame(filas, columns=dg.COLS_CICLO), fuera


def ciclos_activos(maestro: dict, ciclos: pd.DataFrame, t_now: int, hoy: date):
    """Un ciclo en curso por suerte en caña: la soca que está creciendo desde su último corte.

    Edad esperada al corte: la del maestro (próximo − último corte) si es razonable (9-24 meses),
    si no la típica de la suerte (mediana de sus 3 últimos cortes) o la de la planta.
    Caña que ya pasó su edad esperada se estima con la curva completa hasta hoy.
    Devuelve (ciclos en formato `cortes_zqm` + columnas _obs/_edad_hoy/_prox, motivos de descarte).
    """
    tipica = ciclos.sort_values("t_cos").groupby("sec_ste").edad.apply(lambda s: s.tail(3).median())
    por_planta = ciclos[ciclos.anio >= 2019].groupby("planta").edad.median()
    ultima = ciclos.sort_values("harvest").groupby("sec_ste").tail(1).set_index("sec_ste")[["harvest", "corte"]]
    filas, fuera = [], Counter()
    for sec, v in maestro.items():
        if (v.get("uso") or "").strip().upper() not in ("CAÑA", "CANA"):
            fuera["no está en caña"] += 1
            continue
        var = v.get("variedad")
        # "VARIAS" sí se estima: el modelo la aprende como una variedad más (≈ 780 cortes desde 2019)
        if var in (None, "", "RENOVACION"):
            fuera["sin variedad estimable"] += 1
            continue
        cut = _fecha(v.get("fecha_ultimo_corte"))
        corte = v.get("numero_corte")
        if sec in ultima.index:  # el maestro puede ir atrasado frente a la última cosecha registrada
            u = ultima.loc[sec]
            h = date.fromisoformat(u.harvest)
            if h <= hoy and (cut is None or (h - cut).days > 20):
                cut = h
                corte = None if u.corte != u.corte else int(u.corte) + 1
        if cut is None or cut > hoy:
            fuera["sin fecha de último corte"] += 1
            continue
        edad_hoy = (hoy - cut).days / _DIAS
        if edad_hoy < EDAD_MIN:
            fuera[f"muy joven (< {EDAD_MIN} meses)"] += 1
            continue
        prox = _fecha(v.get("fecha_proximo_corte"))
        esp = (prox - cut).days / _DIAS if prox else float("nan")
        if not 9 <= esp <= 24:
            esp = tipica.get(sec)
            esp = esp if esp == esp and esp is not None else por_planta.get(v["planta"], 13.0)
        if edad_hoy >= esp - 0.5:
            obs, edad, t_cos = None, edad_hoy, t_now
        else:
            obs, edad, t_cos = int(edad_hoy), float(esp), _t(cut) + int(round(esp))
        filas.append({
            "sec_ste": sec, "planta": v["planta"], "anio": t_cos // 12, "mes": t_cos % 12 + 1,
            "corte": float(corte) if corte is not None else np.nan, "variedad": var,
            "ha": v.get("area_neta_ha"), "edad": edad, "tch": np.nan, "tipo_cosecha": None,
            "t_cos": t_cos, "t_cut": _t(cut), "harvest": date(t_cos // 12, t_cos % 12 + 1, 15).isoformat(),
            "cut": cut.isoformat(), "key": f"{sec}|en curso", "_obs": obs, "_edad_hoy": edad_hoy,
            "_prox": prox.isoformat() if prox else None,
        })
    return pd.DataFrame(filas), fuera


def entrenar(hist: pd.DataFrame, campana: int, arboles: int = 600) -> MotorTCH:
    tr = hist[hist._anio.between(2019, campana - 1)]
    return MotorTCH(n_estimators=arboles).entrenar(dg.rasgos(tr, QUITAR), tr._tch.values)


def factor_campana(motor: MotorTCH, hist: pd.DataFrame, campana: int):
    """Factor por planta con las cosechas cerradas de la campaña (curva completa, fuera de muestra)."""
    cerr = hist[(hist._anio == campana) & (hist._obs == "completo")].copy()
    if not len(cerr):
        return {}, cerr.assign(pred=[])
    cerr["pred"] = motor.predecir(dg.rasgos(cerr, QUITAR))
    out = {}
    for planta, g in cerr.groupby("_planta"):
        real, est = (g._tch * g._ha).sum(), (g.pred * g._ha).sum()
        k = real / est if len(g) >= RECAL_MIN else 1.0
        ape = (g.pred - g._tch).abs() / g._tch
        out[planta] = {
            "factor": round(float(k), 4), "cosechas": int(len(g)), "area_ha": round(float(g._ha.sum()), 1),
            "tch_real": round(float(real / g._ha.sum()), 1), "tch_modelo": round(float(est / g._ha.sum()), 1),
            "sesgo_modelo_pct": round(float((est / real - 1) * 100), 1),
            "mape_modelo_pct": round(float(ape.mean() * 100), 1),
            "dentro_20_pct": round(float((ape <= 0.2).mean() * 100)),
            "aplica": bool(len(g) >= RECAL_MIN),
        }
    return out, cerr


def estimar(motor: MotorTCH, filas: pd.DataFrame, activos: pd.DataFrame, factores: dict,
            fecha: str) -> list[dict]:
    """Filas de estimados con el mismo esquema que usaba `tch_estimado`."""
    if not len(filas):
        return []
    media, std = motor.predecir_con_banda(dg.rasgos(filas, QUITAR))
    info = activos.set_index("key").to_dict("index")
    out = []
    for r, mu, sd in zip(filas[dg.META].to_dict("records"), media, std):
        a = info[r["_key"]]
        k = factores.get(r["_planta"], {}).get("factor", 1.0)
        tch = round(float(mu) * k, 1)
        area = a["ha"] if a["ha"] is not None and a["ha"] == a["ha"] else None
        out.append({
            "sec_ste": r["_sec"], "planta": r["_planta"], "fecha_corrida": fecha,
            "fecha_corte_prevista": a["_prox"] or a["harvest"], "edad_meses": round(float(a["_edad_hoy"]), 1),
            "soca": int(a["corte"]) if a["corte"] == a["corte"] else None, "variedad": a["variedad"],
            "tch_estimado": tch, "tch_std": round(float(sd) * k, 1),
            "ton_estimadas": round(tch * float(area)) if area else None, "area_ha": area,
            "modo": "motor", "factor_recal": k, "modelo_version": VERSION,
            "edad_obs": r["_obs"],
        })
    return out


def reales(cerr: pd.DataFrame, campana: int) -> list[dict]:
    """Cosechas cerradas de la campaña (ZQM y complemento), una por suerte (la más reciente).
    `tch_modelo` es lo que el modelo estimaba sin conocer el real y antes del factor de campaña."""
    out = {}
    for r in cerr.sort_values(["_mes"]).to_dict("records"):
        var, edad = r.get("variedad"), r.get("edad")
        out[r["_sec"]] = {
            "sec_ste": r["_sec"], "planta": r["_planta"], "campana": str(campana), "anio": int(r["_anio"]),
            "mes": int(r["_mes"]), "corte": int(r["corte"]) if r["corte"] == r["corte"] else None,
            "variedad": var if isinstance(var, str) else None,
            "edad_meses": round(float(edad), 1) if edad is not None and edad == edad else None,
            "tch_real": round(float(r["_tch"]), 1), "area_ha": round(float(r["_ha"]), 2),
            "tch_modelo": round(float(r["pred"]), 1),
            "tipo_cosecha": r["_tipo"] if isinstance(r["_tipo"], str) else None,
        }
    return list(out.values())


def curvas(c: pd.DataFrame, m: pd.DataFrame, estimados: list[dict], desde: int = 2019) -> dict:
    """{sec_ste: [{campana, soca, edad_meses, tch_inst}]}: TCH del ciclo × EVI(edad)/EVI pico, con
    los picos aislados de nube corregidos. El ciclo en curso usa el TCH estimado."""
    c = c.sort_values(["sec_ste", "t_cos"]).reset_index(drop=True)
    est = {e["sec_ste"]: e["tch_estimado"] for e in estimados}
    L = dg.dosel_por_edad(c, m)
    out: dict = {}
    for i, g in L.groupby("i"):
        r = c.iloc[i]
        en_curso = str(r.key).endswith("en curso")
        if r.anio < desde and not en_curso:
            continue
        tch = est.get(r.sec_ste) if en_curso else r.tch
        # el mes del corte (a=0) y el de la cosecha mezclan caña madura con suelo: se omiten
        ultimo = 99 if en_curso else int(round(r.edad)) - 1
        pares = [(int(a), float(v)) for a, v in zip(g.a, g.EVI) if v == v and 1 <= a <= ultimo]
        if tch is None or tch != tch or len(pares) < 3:
            continue
        pares = limpiar_nube(pares)
        pico = max(v for _, v in pares)
        if pico <= 0:
            continue
        campana = f"{r.anio} · en curso" if en_curso else str(int(r.anio))
        soca = int(r.corte) if r.corte == r.corte else None
        out.setdefault(r.sec_ste, []).extend(
            {"campana": campana, "soca": soca, "edad_meses": a, "tch_inst": round(tch * v / pico, 1)}
            for a, v in pares)
    return out


def _limpio(x):
    if isinstance(x, dict):
        return {k: _limpio(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_limpio(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if math.isnan(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def escribir(carpeta, estimados, reales_, factores, curvas_, meta) -> None:
    carpeta = Path(carpeta)
    (carpeta / "curvas").mkdir(parents=True, exist_ok=True)
    (carpeta / "historial").mkdir(parents=True, exist_ok=True)

    def dump(ruta, obj):
        ruta.write_text(json.dumps(_limpio(obj), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    dump(carpeta / "estimados.json", estimados)
    dump(carpeta / "historial" / f"estimados_{meta['fecha_corrida']}.json", estimados)
    dump(carpeta / "reales.json", reales_)
    dump(carpeta / "factores.json", factores)
    dump(carpeta / "meta.json", meta)
    for viejo in (carpeta / "curvas").glob("*.json"):  # carpeta generada por esta corrida
        viejo.unlink()
    for sec, filas in curvas_.items():
        dump(carpeta / "curvas" / f"{sec}.json", filas)
