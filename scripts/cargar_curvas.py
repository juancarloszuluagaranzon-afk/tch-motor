# -*- coding: utf-8 -*-
"""Rellena tch_curva con las curvas de desarrollo de los ciclos que tienen serie
satelital guardada en data/dataset_entrenamiento.jsonl (503 ciclos históricos,
sin satélite). tch_inst = TCH_ciclo · EVI(edad)/EVI_pico (interpretación A).

Requisito: aplicar sql/0004_tch_curva.sql en el SQL Editor de Rio Map.
Uso: python scripts/cargar_curvas.py [--dry] [--sin-filtro] [--umbral 0.30]

Filtro de nube (por defecto ON): corrige artefactos de nube/sombra en la serie de
EVI. Sólo toca picos/valles AISLADOS (un punto que se sale del rango de sus dos
vecinos y se desvía más de `umbral` de la interpolación lineal entre ellos), tanto
caídas (nube/sombra bajan el EVI) como subidas falsas (nube brillante lo sube y
falsearía el EVI_pico). Los descensos/ascensos SOSTENIDOS —varios puntos seguidos,
que son señal real de estrés, riego, maduración o senescencia— NO se tocan.
"""
import argparse, json, sys
from datetime import date

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")
from tchmotor import Supabase
import correr_estimados as ce

DS = r"C:\Users\Agr349\tch-motor\data\dataset_entrenamiento.jsonl"


def d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def limpiar_nube(pts, umbral):
    """Corrige artefactos de nube en la serie de EVI.

    pts: lista de (fecha, edad, evi) ordenada por edad.
    Un punto se considera nube (o nube brillante) sólo si es un pico/valle AISLADO
    —queda fuera del rango [min, max] de sus dos vecinos— y además se desvía más de
    `umbral` (fracción) de la interpolación lineal de esos vecinos. En ese caso se
    reemplaza por la interpolación. Un solo pase: los tramos sostenidos (señal real)
    quedan intactos porque sus puntos no son extremos aislados.
    Devuelve (evi_por_fecha, n_corregidos).
    """
    evi = {f: v for (f, e, v) in pts}
    n = 0
    for i in range(1, len(pts) - 1):
        (f0, e0, v0), (f1, e1, v1), (f2, e2, v2) = pts[i - 1], pts[i], pts[i + 1]
        if e2 == e0:
            continue
        lin = v0 + (v2 - v0) * (e1 - e0) / (e2 - e0)
        if lin <= 0:
            continue
        aislado = v1 < min(v0, v2) or v1 > max(v0, v2)
        if aislado and abs(v1 - lin) / lin > umbral:
            evi[f1] = round(lin, 4)
            n += 1
    return evi, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--sin-filtro", action="store_true", help="no corrige picos de nube")
    ap.add_argument("--umbral", type=float, default=0.30,
                    help="desviación relativa contra la interpolación de vecinos para marcar nube")
    args = ap.parse_args()
    filtrar = not args.sin_filtro
    total_corr = 0
    filas = []
    for line in open(DS, encoding="utf-8"):
        r = json.loads(line)
        cut = d(r.get("cut")); cur = r.get("curves") or {}
        if not cut or not cur.get("EVI"):
            continue
        tch = r.get("tch")
        # índices por fecha
        by_f = {}
        for idx in ("NDVI", "NDMI", "EVI"):
            for p in cur.get(idx, []):
                f = d(p.get("from")); v = p.get("mean")
                if f is None or v is None:
                    continue
                by_f.setdefault(f, {})[idx] = v
        # serie EVI ordenada por edad, dentro del rango del ciclo
        serie = []
        for f, ix in by_f.items():
            if "EVI" not in ix:
                continue
            edad = round((f - cut).days / 30.44, 1)
            if edad < 0 or edad > 16:
                continue
            serie.append((f, edad, ix["EVI"]))
        serie.sort(key=lambda t: t[1])
        if not serie:
            continue
        if filtrar:
            evi_lim, ncorr = limpiar_nube(serie, args.umbral)
            total_corr += ncorr
        else:
            evi_lim = {f: v for (f, e, v) in serie}
        evi_pico = max(evi_lim.values())
        if not evi_pico or evi_pico <= 0:
            continue
        for f, edad, _ in serie:
            ix = by_f[f]
            evi = evi_lim[f]
            tch_inst = round(tch * evi / evi_pico, 1) if (tch and evi is not None) else None
            filas.append({
                "sec_ste": r["sec_ste"], "campana": str(r.get("anio")), "soca": r.get("corte"),
                "variedad": r.get("variedad"), "fecha": f.isoformat(), "edad_meses": edad,
                "ndvi": round(ix["NDVI"], 3) if "NDVI" in ix else None,
                "ndmi": round(ix["NDMI"], 3) if "NDMI" in ix else None,
                "evi": round(evi, 3) if evi is not None else None,
                "tch_inst": tch_inst, "tch_ciclo": round(tch, 1) if tch else None, "fuente": "dataset",
            })
    ciclos = len({(x["sec_ste"], x["campana"]) for x in filas})
    print(f"puntos de curva: {len(filas)} | ciclos (suerte×campaña): {ciclos}"
          + (f" | puntos corregidos por nube: {total_corr}" if filtrar else " | SIN filtro de nube"))
    if args.dry:
        for x in filas[:4]:
            print("  ", x)
        print("[dry] no se escribió. Aplica sql/0004_tch_curva.sql antes de cargar.")
        return
    url = ce._env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_URL")
    svc = ce._env(r"C:\Users\Agr349\turnos-jornales\.env.local", "RIOMAP_SERVICE_ROLE_KEY")
    sb = Supabase(url=url, key=svc)
    n = 0
    for i in range(0, len(filas), 500):
        n += sb.upsert("tch_curva", filas[i:i + 500], on_conflict="sec_ste,campana,fecha")
    print(f"cargados {n} puntos en tch_curva ({ciclos} curvas de desarrollo).")


if __name__ == "__main__":
    main()
