"""Corre el modelo sobre TODAS las cosechas 2019-2025, out-of-sample.

Para cada año Y, entrena el motor SIN ese año (leave-year-out) y predice todas
las cosechas de Y (reconstruidas del ZQM: sec, soca, variedad, edad, mes →
ventana de curva; zona del maestro; tab_id del índice). 2026 ya está en
producción (tch_estimado), no se repite aquí. Escribe incremental (resiliente).

Salida: C:\\Users\\Agr349\\Documents\\Estimados_historico.csv
"""
import argparse, csv, io, os, sys, json
from datetime import date, timedelta
import numpy as np, pandas as pd, openpyxl

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")
from tchmotor import (Supabase, AforoSinteticoTabla, build_features, MotorTCH,
                      curva_suerte, map_variedad)
import correr_estimados as ce

ZQM = r"C:\Users\Agr349\Documents\historico zqm.xlsx"
MAESTRO = r"C:\Users\Agr349\agrocontrol-campo\public\data"
IDX = r"C:\Users\Agr349\tch-motor\data\tablones_index.json"
DS = r"C:\Users\Agr349\tch-motor\data\dataset_entrenamiento.jsonl"
OUT = r"C:\Users\Agr349\Documents\Estimados_historico.csv"
C_ANIO, C_SEC, C_MES, C_CORTE, C_VAR, C_AREA, C_EDAD, C_TCTOT, C_TCH = 1, 3, 4, 15, 16, 17, 18, 20, 21
_DIAS = 30.44
AÑOS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]


def num(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return np.nan


def cosechas(anio):
    wb = openpyxl.load_workbook(ZQM, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    best = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if str(row[C_ANIO]) != str(anio):
            continue
        sec = row[C_SEC]
        tch, tct, area, edad = num(row[C_TCH]), num(row[C_TCTOT]), num(row[C_AREA]), num(row[C_EDAD])
        if not sec or np.isnan(tch) or np.isnan(area) or np.isnan(edad):
            continue
        sec = str(sec).strip()
        if sec not in best or (tct or 0) > best[sec]["_t"]:
            best[sec] = {"tch_real": tch, "area": area, "edad": edad, "mes": num(row[C_MES]),
                         "corte": num(row[C_CORTE]), "var": str(row[C_VAR]).strip() if row[C_VAR] else None, "_t": tct or 0}
    wb.close()
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lote", type=int, default=40)
    args = ap.parse_args()
    os.environ.setdefault("TCH_SUPABASE_URL", ce._env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_URL"))
    os.environ.setdefault("TCH_SUPABASE_KEY", ce._env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_ANON_KEY"))
    sb = Supabase()
    vm = sb.cargar_var_map()
    synth = AforoSinteticoTabla(sb.cargar_aforo_sintetico())

    maestro = {}
    for fn in ("maestro_suertes.json", "maestro_castilla.json"):
        maestro.update(json.load(open(os.path.join(MAESTRO, fn), encoding="utf-8")))
    idx = json.load(open(IDX, encoding="utf-8"))

    # pool de entrenamiento (504 eventos con features + año + tch)
    Xrows, ys, gs = [], [], []
    for line in open(DS, encoding="utf-8"):
        r = json.loads(line)
        if not r["curves"].get("NDVI"):
            continue
        f = build_features(r, synth, vm)
        if f.get("ndvi_n", 0) < 3:
            continue
        Xrows.append(f); ys.append(r["tch"]); gs.append(int(r["anio"]))
    Xpool = pd.DataFrame(Xrows); ypool = np.array(ys); gpool = np.array(gs)
    print(f"pool de entrenamiento: {len(ypool)} eventos", flush=True)

    cols = ["anio", "sec_ste", "planta", "variedad", "soca", "edad_meses", "area_ha",
            "tch_estimado", "tch_std", "tch_real", "error_tha", "error_pct", "modo", "fuente"]
    fh = open(OUT, "w", encoding="utf-8-sig", newline="")
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); fh.flush()

    for Y in AÑOS:
        # motor leave-year-out
        mask = gpool != Y
        motor = MotorTCH(n_estimators=600).entrenar(Xpool[mask], ypool[mask])
        cos = cosechas(Y)
        suertes = []
        for sec, c in cos.items():
            if sec not in idx or c["var"] in (None, "V19", "VARIAS", "RENOVACION"):
                continue
            tab_id, _h, planta = idx[sec]
            mes = int(c["mes"]) if c["mes"] and not np.isnan(c["mes"]) else 9
            harvest = date(Y, min(max(mes, 1), 12), 15)
            cut = (harvest - timedelta(days=float(c["edad"]) * _DIAS)).isoformat()
            zona = (maestro.get(sec) or {}).get("zona_agroecologica")
            suertes.append({"sec": sec, "planta": planta, "tab_id": tab_id, "cut": cut,
                            "harvest": harvest.isoformat(), "edad": round(float(c["edad"]), 1),
                            "corte": int(c["corte"]) if c["corte"] and not np.isnan(c["corte"]) else None,
                            "var": c["var"], "zona": zona, "area": c["area"], "real": c["tch_real"]})
        print(f"\n=== {Y}: {len(suertes)} cosechas (entrena sin {Y}, n={mask.sum()}) ===", flush=True)
        hechas = 0
        for i in range(0, len(suertes), args.lote):
            lote = suertes[i:i + args.lote]
            feats, meta = [], []
            for s in lote:
                try:
                    curves = curva_suerte(s["tab_id"], s["planta"], s["cut"], s["harvest"])
                except Exception:
                    curves = None
                if not curves:
                    continue
                f = build_features({"variedad": s["var"], "corte": s["corte"], "edad": s["edad"],
                                    "zona_agro": s["zona"], "ha": s["area"], "mes": int(s["harvest"][5:7]),
                                    "cut": s["cut"], "curves": curves}, synth, vm)
                if f.get("ndvi_n", 0) < 3:
                    continue
                feats.append(f); meta.append(s)
            if feats:
                mu, sd = motor.predecir_con_banda(pd.DataFrame(feats))
                for s, e, band in zip(meta, mu, sd):
                    e = round(float(e), 1); r = s["real"]
                    w.writerow({"anio": Y, "sec_ste": s["sec"], "planta": s["planta"],
                                "variedad": map_variedad(s["var"], vm), "soca": s["corte"],
                                "edad_meses": s["edad"], "area_ha": round(s["area"], 2),
                                "tch_estimado": e, "tch_std": round(float(band), 1),
                                "tch_real": round(r, 1) if r else None,
                                "error_tha": round(e - r, 1) if r else None,
                                "error_pct": round((e - r) / r * 100, 1) if r else None,
                                "modo": "motor", "fuente": "out-of-sample (leave-year-out)"})
                    hechas += 1
                fh.flush()
            print(f"  [{Y} {min(i + args.lote, len(suertes))}/{len(suertes)}] acum {hechas}", flush=True)
        print(f"  {Y} listo: {hechas} estimadas", flush=True)
    fh.close()
    print(f"\nTODO listo → {OUT}", flush=True)


if __name__ == "__main__":
    main()
