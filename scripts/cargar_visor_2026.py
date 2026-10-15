"""Deja el visor con la campaña 2026 COMPLETA:
- 607 cortes reales (del zqm 26)  -> tch_real
- 691 suertes por cosechar con proyección corregida (modelo si madura, historia si
  joven, promedio campaña si nada) -> tch_estimado (misma corrida, upsert).

Escritura con service_role. Uso: python scripts/cargar_visor_2026.py [--dry]
"""
import argparse, io, os, sys, json
import numpy as np, openpyxl

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")
from tchmotor import Supabase, cargar_var_map, map_variedad
import correr_estimados as ce

MA = r"C:\Users\Agr349\agrocontrol-campo\public\data"
SCR = r"C:\Users\Agr349\AppData\Local\Temp\claude\C--Users-Agr349\b8086a2a-b9e9-4689-9102-380331880077\scratchpad"
ZQM26 = r"C:\Users\Agr349\Documents\zqm 26.xlsx"
HIST = r"C:\Users\Agr349\Documents\historico zqm.xlsx"
CORRIDA = "2026-09-09"


def num(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return np.nan


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    vm = cargar_var_map()

    # --- reales 2026 del zqm 26 ---
    wb = openpyxl.load_workbook(ZQM26, read_only=True, data_only=True)
    ws = wb["ZQM101"]; best = {}; t26 = []; a26 = []
    for row in ws.iter_rows(min_row=11, values_only=True):
        sec = row[2]; tch = num(row[20]); tct = num(row[19]); area = num(row[16])
        if not sec or np.isnan(tch) or np.isnan(area) or area <= 0:
            continue
        sec = str(sec).strip()
        planta = str(row[45]).strip().lower() if row[45] else ""
        planta = "castilla" if planta.startswith("cast") else ("riopaila" if planta.startswith("riop") else planta)
        if sec not in best or (tct or 0) > best[sec]["_t"]:
            best[sec] = {"tch": tch, "_t": tct or 0, "area": area, "tct": tct,
                         "corte": num(row[14]), "var": str(row[15]).strip() if row[15] else None, "planta": planta}
        t26.append(tch); a26.append(area)
    wb.close()
    avg26 = float(np.average(t26, weights=a26))
    reales = [{"sec_ste": s, "campana": "2026", "planta": r["planta"],
               "corte": int(r["corte"]) if r["corte"] and not np.isnan(r["corte"]) else None,
               "variedad": map_variedad(r["var"], vm), "area_ha": round(r["area"], 2),
               "tc_total": round(r["tct"], 1) if r["tct"] else None, "tch_real": round(r["tch"], 1),
               "fecha_corte_real": None, "fuente": "zqm_2026"} for s, r in best.items()]
    cortadas = set(best)

    # --- historia por suerte ---
    wb = openpyxl.load_workbook(HIST, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]; by = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        sec = row[3]; tch = num(row[21])
        if sec and not np.isnan(tch):
            by.setdefault(str(sec).strip(), []).append(tch)
    wb.close()
    hist = {s: float(np.mean(v)) for s, v in by.items()}

    # --- maestro corte 2026 no cortadas + estimado del modelo ---
    maestro, plantas = {}, {}
    for fn, pl in (("maestro_suertes.json", "riopaila"), ("maestro_castilla.json", "castilla")):
        for sec, v in json.load(open(os.path.join(MA, fn), encoding="utf-8")).items():
            maestro[sec] = v; plantas[sec] = pl
    est = {r["sec_ste"]: r for r in json.load(open(SCR + r"\est_full2.json"))}

    def a2026(v):
        try:
            return int(str(v.get("fecha_proximo_corte"))[:4]) == 2026
        except Exception:
            return False

    estimados = []
    for s, v in maestro.items():
        if s in cortadas or not a2026(v) or (v.get("uso") or "").strip().upper() not in ("CAÑA", "CANA"):
            continue
        area = num(v.get("area_neta_ha")) or 0
        if area <= 0:
            continue
        e = est.get(s)
        if e and (e.get("edad_meses") or 0) >= 10:
            tch = round(e["tch_estimado"], 1); modo = e.get("modo", "motor"); band = e.get("tch_std")
        elif s in hist:
            tch = round(hist[s], 1); modo = "historia"; band = None
        else:
            tch = round(avg26, 1); modo = "promedio"; band = None
        estimados.append({"sec_ste": s, "planta": plantas[s], "fecha_corrida": CORRIDA,
                          "fecha_corte_prevista": str(v.get("fecha_proximo_corte"))[:10] if v.get("fecha_proximo_corte") else None,
                          "edad_meses": v.get("edad_csv"), "soca": v.get("numero_corte"),
                          "variedad": v.get("variedad"), "tch_estimado": tch, "tch_std": band,
                          "ton_estimadas": round(tch * area, 0), "area_ha": round(area, 2),
                          "modo": modo, "factor_recal": None, "modelo_version": "v0.1"})

    print(f"reales 2026 a cargar: {len(reales)} (TCH prom campaña {avg26:.1f})")
    print(f"estimados 2026 corregidos a cargar: {len(estimados)} "
          f"({sum(1 for e in estimados if e['modo'] in ('motor','fusion'))} modelo, "
          f"{sum(1 for e in estimados if e['modo']=='historia')} historia, "
          f"{sum(1 for e in estimados if e['modo']=='promedio')} promedio)")
    if args.dry:
        print("[dry] no se escribió.")
        return

    os.environ.setdefault("TCH_SUPABASE_URL", ce._env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_URL"))
    os.environ.setdefault("TCH_SUPABASE_KEY", ce._env(r"C:\Users\Agr349\turnos-jornales\.env.local", "RIOMAP_SERVICE_ROLE_KEY"))
    sb = Supabase()
    for i in range(0, len(reales), 200):
        sb.guardar_reales(reales[i:i + 200])
    print(f"escritos {len(reales)} reales en tch_real")
    for i in range(0, len(estimados), 200):
        sb.guardar_estimados(estimados[i:i + 200])
    print(f"escritos {len(estimados)} estimados corregidos en tch_estimado")


if __name__ == "__main__":
    main()
