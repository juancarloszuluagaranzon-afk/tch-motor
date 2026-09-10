"""Carga a tch_real los cortes reales de la validación RIOCAS (sep-2026).

Estos reales vienen de la hoja de validación del usuario (TCH Real = TC-Total/área),
no del ZQM (que aún no trae 2026). Toma variedad/soca/área del tch_estimado ya
escrito. Requiere que el SQL 0002 (tabla tch_real) esté aplicado.

Uso:
  python scripts/cargar_reales_validacion.py --dry   # solo arma y muestra
  python scripts/cargar_reales_validacion.py         # escribe en tch_real
"""
import argparse, json, os, sys
sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")
from tchmotor import Supabase
import correr_estimados as ce  # deja stdout en UTF-8

# TCH real (=TC-Total/área) + fecha de corte, de la hoja de validación.
REAL = {
    "2141-070": (74, "2026-09-05"), "2111-321": (121, "2026-09-01"),
    "2111-210": (100, "2026-09-01"), "2695-220": (96, "2026-09-01"),
    "2109-142": (103, "2026-09-04"), "2109-163": (102, "2026-09-01"),
    "2111-424": (94, "2026-09-01"), "2506-121": (93, "2026-09-01"),
    "2506-123": (87, "2026-09-04"), "2695-201": (90, "2026-09-01"),
    "2101-010": (110, "2026-09-05"), "2101-071": (89, "2026-09-06"),
    "2101-102": (93, "2026-09-05"), "2109-020": (147, "2026-09-04"),
    "2109-060": (128, "2026-09-04"), "2138-040": (93, "2026-09-04"),
    "2138-051": (57, "2026-09-04"), "2141-040": (84, "2026-09-06"),
    "2503-088": (113, "2026-09-06"), "2503-200": (121, "2026-09-06"),
}
CAMPANA = "2026"
DATA = r"C:\Users\Agr349\tch-motor\data\reales_validacion_2026.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("TCH_SUPABASE_URL", ce._env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_URL"))
    os.environ.setdefault("TCH_SUPABASE_KEY", ce._env(r"C:\Users\Agr349\turnos-jornales\.env.local", "RIOMAP_SERVICE_ROLE_KEY"))
    sb = Supabase()

    # variedad/soca/área del estimado ya escrito
    secs = ",".join(REAL)
    est = {r["sec_ste"]: r for r in sb.leer("tch_estimado", select="sec_ste,planta,variedad,soca,area_ha", **{"sec_ste": f"in.({secs})"})}

    filas = []
    for sec, (tch, fecha) in REAL.items():
        e = est.get(sec, {})
        area = e.get("area_ha")
        filas.append({
            "sec_ste": sec, "campana": CAMPANA, "planta": e.get("planta", "castilla"),
            "corte": e.get("soca"), "variedad": e.get("variedad"),
            "area_ha": area, "tc_total": round(tch * area, 1) if area else None,
            "tch_real": tch, "fecha_corte_real": fecha, "fuente": "validacion_riocas",
        })
    json.dump(filas, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"armadas {len(filas)} filas → {DATA}")
    for f in filas[:5]:
        print(" ", {k: f[k] for k in ("sec_ste", "variedad", "tch_real", "area_ha", "tc_total")})
    if args.dry:
        print("[dry] no se escribió tch_real.")
        return
    n = sb.guardar_reales(filas)
    print(f"escritas {n} filas en tch_real (campaña {CAMPANA}).")


if __name__ == "__main__":
    main()
