# -*- coding: utf-8 -*-
"""LISTO PARA DISPARAR cuando vuelva la cuota de satelite (CDSE).

Agrega las cosechas cerradas de un ano (por defecto 2026, incluye septiembre en
cuanto el ZQM las traiga) al dataset de entrenamiento, para el proximo
reentrenamiento del modelo. Extrae la curva satelital del ciclo cortado y arma
el registro con el MISMO esquema de data/dataset_entrenamiento.jsonl.

- Idempotente: salta las que ya estan en el dataset (por key sec|anio|corte).
- Resiliente: descarga en paralelo, escribe incremental, hace backup antes.
- Chequea la cuota: si el endpoint responde 403 (sin PU), aborta sin tocar nada.

Uso:
  python scripts/agregar_cosechas_al_dataset.py --dry            # cuenta, no llama satelite
  python scripts/agregar_cosechas_al_dataset.py --anio 2026      # dispara (necesita cuota)
  python scripts/agregar_cosechas_al_dataset.py --anio 2026 --zqm "C:\\...\\zqm 26.xlsx"
"""
import argparse, json, os, sys, shutil
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
import numpy as np, openpyxl

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")
from tchmotor import curva_suerte, map_variedad, cargar_var_map
from tchmotor.extraccion import serie_indice
import correr_estimados as ce

DS = r"C:\Users\Agr349\tch-motor\data\dataset_entrenamiento.jsonl"
IDX = r"C:\Users\Agr349\tch-motor\data\tablones_index.json"
MAESTRO = r"C:\Users\Agr349\agrocontrol-campo\public\data"
ZQM_HIST = r"C:\Users\Agr349\Documents\historico zqm.xlsx"
ZQM_2026 = r"C:\Users\Agr349\Documents\zqm 26.xlsx"
_DIAS = 30.44
# columnas: hist y zqm26 tienen layout distinto
COLS = {
    "hist": dict(anio=1, sec=3, mes=4, corte=15, var=16, area=17, edad=18, tct=20, tch=21, hoja=None, row0=2),
    "2026": dict(anio=None, sec=2, mes=3, corte=14, var=15, area=16, edad=17, tct=19, tch=20, hoja="ZQM101", row0=11),
}


def num(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return np.nan


def cuota_ok():
    """True si el endpoint de satelite responde con serie (no 403)."""
    idx = json.load(open(IDX, encoding="utf-8"))
    tab, _h, planta = next(iter(idx.values()))
    s = serie_indice(tab, planta, "NDVI", "2024-01-01", "2024-12-15", reintentos=1)
    return s is not None


def leer_cosechas(zqm, anio, layout):
    c = COLS[layout]
    wb = openpyxl.load_workbook(zqm, read_only=True, data_only=True)
    ws = wb[c["hoja"]] if c["hoja"] else wb[wb.sheetnames[0]]
    best = {}
    for row in ws.iter_rows(min_row=c["row0"], values_only=True):
        if c["anio"] is not None and str(row[c["anio"]]) != str(anio):
            continue
        sec = row[c["sec"]]
        tch, tct, area, edad = num(row[c["tch"]]), num(row[c["tct"]]), num(row[c["area"]]), num(row[c["edad"]])
        if not sec or np.isnan(tch) or np.isnan(area) or area <= 0 or np.isnan(edad):
            continue
        sec = str(sec).strip()
        if sec not in best or (tct or 0) > best[sec]["_t"]:
            best[sec] = {"tch": tch, "area": area, "edad": edad, "mes": num(row[c["mes"]]),
                         "corte": num(row[c["corte"]]), "var": str(row[c["var"]]).strip() if row[c["var"]] else None, "_t": tct or 0}
    wb.close()
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anio", type=int, default=2026)
    ap.add_argument("--zqm", default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    layout = "2026" if args.anio == 2026 else "hist"
    zqm = args.zqm or (ZQM_2026 if args.anio == 2026 else ZQM_HIST)

    vm = cargar_var_map()
    idx = json.load(open(IDX, encoding="utf-8"))
    maestro = {}
    for fn in ("maestro_suertes.json", "maestro_castilla.json"):
        maestro.update(json.load(open(os.path.join(MAESTRO, fn), encoding="utf-8")))
    ya = set()
    for line in open(DS, encoding="utf-8"):
        try:
            ya.add(json.loads(line)["key"])
        except Exception:
            pass

    cos = leer_cosechas(zqm, args.anio, layout)
    pend = []
    for sec, c in cos.items():
        if sec not in idx or c["var"] in (None, "V19", "VARIAS", "RENOVACION"):
            continue
        corte = int(c["corte"]) if c["corte"] and not np.isnan(c["corte"]) else None
        key = f"{sec}|{args.anio}|{corte}"
        if key in ya:
            continue
        tab_id, _h, planta = idx[sec]
        mes = int(c["mes"]) if c["mes"] and not np.isnan(c["mes"]) else 9
        harvest = date(args.anio, min(max(mes, 1), 12), 15)
        cut = (harvest - timedelta(days=float(c["edad"]) * _DIAS)).isoformat()
        m = maestro.get(sec) or {}
        pend.append({"key": key, "sec_ste": sec, "planta": planta, "tab_id": tab_id,
                     "ha": round(c["area"], 2), "tch": round(c["tch"], 2), "corte": corte,
                     "edad": round(float(c["edad"]), 1), "variedad": c["var"],
                     "zona": m.get("zona"), "zona_agro": m.get("zona_agroecologica"),
                     "anio": args.anio, "mes": mes, "cut": cut, "harvest": harvest.isoformat()})

    print(f"cosechas {args.anio} en ZQM con tablon: {len([s for s in cos if s in idx])} | ya en dataset: se saltan | NUEVAS a agregar: {len(pend)}", flush=True)
    if args.dry:
        print("[dry] no se llama satelite ni se escribe. Ejemplos:")
        for p in pend[:3]:
            print("  ", p["key"], p["variedad"], "edad", p["edad"], "cut", p["cut"])
        return
    if not pend:
        print("nada nuevo que agregar."); return

    if not cuota_ok():
        print("CUOTA CDSE AGOTADA (403). Abortado: no se toco el dataset. Reintenta cuando se reponga la cuota."); return

    def bajar(p):
        try:
            return p, curva_suerte(p["tab_id"], p["planta"], p["cut"], p["harvest"])
        except Exception:
            return p, None

    shutil.copy(DS, DS + ".bak")
    print(f"backup -> {DS}.bak", flush=True)
    pool = ThreadPoolExecutor(max_workers=args.workers)
    add = 0; sin = 0
    with open(DS, "a", encoding="utf-8") as fh:
        for i in range(0, len(pend), 48):
            for p, curves in pool.map(bajar, pend[i:i + 48]):
                if not curves or not curves.get("NDVI") or len([x for x in curves["NDVI"] if x.get("mean") is not None]) < 3:
                    sin += 1; continue
                rec = {"key": p["key"], "sec_ste": p["sec_ste"], "planta": p["planta"], "tab_id": p["tab_id"],
                       "ha": p["ha"], "tch": p["tch"], "corte": p["corte"], "edad": p["edad"],
                       "variedad": p["variedad"], "zona": p["zona"], "zona_agro": p["zona_agro"],
                       "anio": p["anio"], "mes": p["mes"], "cut": p["cut"], "harvest": p["harvest"], "curves": curves}
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); add += 1
            fh.flush()
            print(f"  [{min(i+48,len(pend))}/{len(pend)}] agregadas {add} | sin senal {sin}", flush=True)
    print(f"\nlisto: {add} cosechas {args.anio} agregadas al dataset ({sin} sin senal). Ahora reentrena el modelo.", flush=True)


if __name__ == "__main__":
    main()
