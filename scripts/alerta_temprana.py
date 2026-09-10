"""Alerta temprana de suertes en riesgo (caña en pie 2026).

Cruza dos señales que anticipan una cosecha mala meses antes:
 1) SCORE de la evaluación de 3 meses de ESTA campaña (2025-2026) bajo — flaggea
    problemas de establecimiento/labores (base "CAÑA DE TRES MESES", score 1-5).
 2) DESVÍO CRÓNICO: la suerte rinde histórico por debajo de su variedad×soca
    (de la lista de candidatas a extremo).
Suerte con score 3m bajo + crónica = sospechosa de RSD/fallas de alta confianza.

Salida: CSV priorizado para inspección de agronomía.
  python scripts/alerta_temprana.py --score-max 4.67
"""
import argparse, csv, os, sys
from datetime import date
import numpy as np, openpyxl

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")
from tchmotor import Supabase
import correr_estimados as ce

EVAL3M = r"C:\Users\Agr349\AppData\Local\Temp\BASE CAÑA DE TRES MESES.xlsx"
CANDID = r"C:\Users\Agr349\Documents\suertes_candidatas_extremo_2026.csv"
SALIDA = r"C:\Users\Agr349\Documents\alerta_temprana_2026.csv"


def num(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return np.nan


def evals_3m(desde=2025):
    """{sec: (score, fecha, corte, edad)} — la eval de 3m más reciente >= `desde`."""
    wb = openpyxl.load_workbook(EVAL3M, read_only=True, data_only=True)
    ws = wb["Base"]
    out = {}
    for row in ws.iter_rows(min_row=12, values_only=True):
        sec = row[0]
        if sec is None or str(sec).strip() == "":
            continue
        an = num(row[1])
        if np.isnan(an) or an < desde:
            continue
        sec = str(sec).strip()
        score = num(row[16])         # compuesto 1-5
        corte = num(row[6]); edad = num(row[5])
        fecha = str(row[2])[:10] if row[2] is not None else None
        if np.isnan(score):
            continue
        prev = out.get(sec)
        if prev is None or an >= prev[4]:
            out[sec] = (score, fecha, int(corte) if not np.isnan(corte) else None, edad, int(an))
    wb.close()
    return out


def cronicos():
    """{sec: desvio_cronico_tha} de la lista de candidatas (solo las BAJA/crónicas)."""
    out = {}
    if not os.path.exists(CANDID):
        return out
    with open(CANDID, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            try:
                out[r["sec_ste"]] = float(r["desvio_cronico_tha"])
            except Exception:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score-max", type=float, default=4.67, help="score 3m <= esto = bajo")
    args = ap.parse_args()

    ev = evals_3m()
    cron = cronicos()
    print(f"evals 3m (2025+): {len(ev)} suertes · crónicas en lista: {len(cron)}")

    suertes = {s["sec_ste"]: s for s in ce.cargar_suertes(0, 20, date.today())}
    print(f"suertes en pie: {len(suertes)}")

    est = {}
    try:
        os.environ.setdefault("TCH_SUPABASE_URL", ce._env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_URL"))
        os.environ.setdefault("TCH_SUPABASE_KEY", ce._env(r"C:\Users\Agr349\turnos-jornales\.env.local", "RIOMAP_SERVICE_ROLE_KEY"))
        for r in Supabase().cargar_estimados():
            est[r["sec_ste"]] = r
    except Exception as e:
        print("aviso: sin estimados:", str(e)[:70])

    filas = []
    for sec, s in suertes.items():
        e = ev.get(sec)
        if not e or e[0] > args.score_max:      # sin eval 3m baja de esta campaña
            continue
        score, fecha, corte_ev, edad_ev, anio_ev = e
        dc = cron.get(sec)
        es_cronica = dc is not None and dc <= -10
        cat = "AMBAS (crónica + score bajo)" if es_cronica else "score 3m bajo"
        es = est.get(sec, {})
        area = s.get("area") or s.get("ha") or 0
        filas.append({
            "sec_ste": sec, "planta": s["planta"], "variedad": s.get("variedad"),
            "soca_actual": s.get("corte"), "edad_meses": s.get("edad"), "area_ha": round(area, 2),
            "score_3m": round(score, 2), "fecha_eval_3m": fecha,
            "desvio_cronico_tha": round(dc, 1) if dc is not None else "",
            "tch_estimado_2026": es.get("tch_estimado", ""), "banda_std": es.get("tch_std", ""),
            "categoria": cat,
        })

    # prioridad: AMBAS primero, luego score peor, luego área mayor
    filas.sort(key=lambda f: (0 if f["categoria"].startswith("AMBAS") else 1, f["score_3m"], -f["area_ha"]))
    for i, f in enumerate(filas, 1):
        f["prioridad"] = i

    cols = ["prioridad", "sec_ste", "planta", "variedad", "soca_actual", "edad_meses", "area_ha",
            "score_3m", "fecha_eval_3m", "desvio_cronico_tha", "tch_estimado_2026", "banda_std", "categoria"]
    with open(SALIDA, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for f in filas:
            w.writerow({c: f.get(c, "") for c in cols})

    nb = sum(1 for f in filas if f["categoria"].startswith("AMBAS"))
    print(f"\nalerta temprana: {len(filas)} suertes  ({nb} AMBAS crónica+score, {len(filas)-nb} solo score bajo)")
    print(f"CSV: {SALIDA}\n")
    print(f"{'#':>3} {'suerte':>10} {'pl':>4} {'var':>10} {'soca':>4} {'ha':>6} {'score':>5} {'crónico':>7} {'est':>6}  categoría")
    for f in filas[:18]:
        print(f"{f['prioridad']:>3} {f['sec_ste']:>10} {f['planta'][:3]:>4} {str(f['variedad'])[:10]:>10} "
              f"{str(f['soca_actual']):>4} {f['area_ha']:>6.1f} {f['score_3m']:>5.2f} "
              f"{str(f['desvio_cronico_tha']):>7} {str(f['tch_estimado_2026']):>6}  {f['categoria']}")


if __name__ == "__main__":
    main()
