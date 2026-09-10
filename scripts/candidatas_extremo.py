"""Lista priorizada de suertes candidatas a EXTREMO (para dirigir muestreo de
RSD / fallas de stand).

El motor comprime los extremos (sobreestima las malas, subestima las
excepcionales). Quien mejor los delata es la HISTORIA: una suerte que corte tras
corte rinde por debajo (o por encima) de lo que da su variedad×soca es una
sospechosa crónica — justo donde se esconde el RSD o las fallas, y donde el
modelo más yerra. Priorizamos por toneladas en juego (|desvío|×área).

Salida: CSV ordenado por prioridad. Uso:
  python scripts/candidatas_extremo.py --umbral 10
"""
import argparse, io, os, sys
from datetime import date
import numpy as np, openpyxl

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")
from tchmotor import cargar_var_map, Supabase, map_variedad
import correr_estimados as ce  # al importarse ya deja sys.stdout en UTF-8

ZQM = r"C:\Users\Agr349\Documents\historico zqm.xlsx"
SALIDA = r"C:\Users\Agr349\Documents\suertes_candidatas_extremo_2026.csv"
C_ANIO, C_SEC, C_CORTE, C_VAR, C_AREA, C_TCTOT, C_TCH = 1, 3, 15, 16, 17, 20, 21


def num(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return np.nan


def leer_historia(vm):
    """Por suerte: sus cortes (año, tch, soca, var CC). Y tabla var×soca esperado."""
    wb = openpyxl.load_workbook(ZQM, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    mejor = {}  # (sec, anio) -> (tch, tct, soca, var_cc)
    for row in ws.iter_rows(min_row=2, values_only=True):
        sec, an = row[C_SEC], row[C_ANIO]
        tch, tct = num(row[C_TCH]), num(row[C_TCTOT])
        if not sec or np.isnan(tch):
            continue
        try:
            an = int(an)
        except Exception:
            continue
        soca = num(row[C_CORTE])
        var = map_variedad(str(row[C_VAR]).strip() if row[C_VAR] else None, vm)
        k = (str(sec).strip(), an)
        if k not in mejor or (tct or 0) > mejor[k][1]:
            mejor[k] = (tch, tct or 0, soca, var)
    wb.close()
    # tabla var×soca esperado + var esperado + global
    from collections import defaultdict
    porvs, porv, glob = defaultdict(list), defaultdict(list), []
    hist = defaultdict(list)
    for (sec, an), (tch, _, soca, var) in mejor.items():
        hist[sec].append((an, tch, soca, var))
        glob.append(tch)
        if var:
            porv[var].append(tch)
            if soca is not None and not np.isnan(soca):
                porvs[(var, int(soca))].append(tch)
    gmean = float(np.mean(glob))
    espvs = {k: float(np.mean(v)) for k, v in porvs.items() if len(v) >= 5}
    espv = {k: float(np.mean(v)) for k, v in porv.items() if len(v) >= 5}

    def esperado(var, soca):
        if var and soca is not None and not np.isnan(soca) and (var, int(soca)) in espvs:
            return espvs[(var, int(soca))]
        if var in espv:
            return espv[var]
        return gmean
    return hist, esperado, gmean


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--umbral", type=float, default=10.0, help="|desvío crónico| t/ha para marcar extremo")
    ap.add_argument("--min-anios", type=int, default=2, help="mínimo de cosechas históricas")
    args = ap.parse_args()

    vm = cargar_var_map()
    hist, esperado, gmean = leer_historia(vm)
    print(f"TCH global histórico: {gmean:.1f} t/ha · suertes con historia: {len(hist)}")

    # universo en pie 2026
    suertes = ce.cargar_suertes(0, 20, date.today())
    print(f"suertes en pie (maestro): {len(suertes)}")

    # estimado 2026 actual (si el poblado ya escribió), tolerante
    est = {}
    try:
        os.environ.setdefault("TCH_SUPABASE_URL", ce._env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_URL"))
        os.environ.setdefault("TCH_SUPABASE_KEY", ce._env(r"C:\Users\Agr349\turnos-jornales\.env.local", "RIOMAP_SERVICE_ROLE_KEY"))
        for r in Supabase().cargar_estimados():
            est[r["sec_ste"]] = r
        print(f"estimados 2026 disponibles: {len(est)}")
    except Exception as e:
        print("aviso: sin estimados 2026 aún:", str(e)[:80])

    filas = []
    for s in suertes:
        h = hist.get(s["sec_ste"])
        if not h or len(h) < args.min_anios:
            continue
        # desvío crónico = media de (tch_i - esperado(var_i, soca_i))
        resids = [tch - esperado(var, soca) for (_, tch, soca, var) in h]
        cron = float(np.mean(resids))
        hmean = float(np.mean([tch for (_, tch, _, _) in h]))
        if abs(cron) < args.umbral:
            continue
        tipo = "BAJA (sospecha RSD/fallas)" if cron < 0 else "ALTA (excepcional)"
        area = s.get("area") or s.get("ha") or 0
        e = est.get(s["sec_ste"])
        filas.append({
            "sec_ste": s["sec_ste"], "planta": s["planta"], "variedad": s.get("variedad"),
            "soca_actual": s.get("corte"), "edad_meses": s.get("edad"), "area_ha": round(area, 2),
            "hist_anios": len(h), "hist_tch_medio": round(hmean, 1),
            "desvio_cronico_tha": round(cron, 1), "tipo": tipo,
            "tch_estimado_2026": (e or {}).get("tch_estimado"),
            "banda_std": (e or {}).get("tch_std"),
            "ton_en_juego": round(abs(cron) * area, 0),
        })

    filas.sort(key=lambda f: f["ton_en_juego"], reverse=True)
    for i, f in enumerate(filas, 1):
        f_prioridad = i
        f["prioridad"] = i

    cols = ["prioridad", "sec_ste", "planta", "variedad", "soca_actual", "edad_meses", "area_ha",
            "hist_anios", "hist_tch_medio", "desvio_cronico_tha", "tipo",
            "tch_estimado_2026", "banda_std", "ton_en_juego"]
    with open(SALIDA, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for f in filas:
            fh.write(",".join(_csv(f.get(c)) for c in cols) + "\n")

    nb = sum(1 for f in filas if f["tipo"].startswith("BAJA"))
    na = len(filas) - nb
    print(f"\ncandidatas a extremo: {len(filas)}  ({nb} BAJA/sospecha RSD, {na} ALTA/excepcional)")
    print(f"toneladas en juego (suma |desvío|×área): {sum(f['ton_en_juego'] for f in filas):,.0f} t")
    print(f"CSV: {SALIDA}\n")
    print("Top 15 por toneladas en juego:")
    print(f"{'#':>3} {'suerte':>10} {'pl':>4} {'var':>10} {'soca':>4} {'ha':>6} {'hist':>6} {'desvío':>7} {'ton_juego':>9}  tipo")
    for f in filas[:15]:
        print(f"{f['prioridad']:>3} {f['sec_ste']:>10} {f['planta'][:3]:>4} {str(f['variedad'])[:10]:>10} "
              f"{str(f['soca_actual']):>4} {f['area_ha']:>6.1f} {f['hist_tch_medio']:>6.1f} "
              f"{f['desvio_cronico_tha']:>+6.1f} {f['ton_en_juego']:>9,.0f}  {f['tipo'][:22]}")


def _csv(v):
    if v is None:
        return ""
    v = str(v)
    return '"' + v.replace('"', '""') + '"' if ("," in v or '"' in v) else v


if __name__ == "__main__":
    main()
