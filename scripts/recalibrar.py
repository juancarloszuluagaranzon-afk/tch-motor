"""Job de auto-recalibración (P5).

Empareja los cortes cerrados (tch_real) con lo estimado (tch_estimado, modo motor),
deriva el factor por planta y lo escribe en tch_factor. El job mensual de estimados
lo lee automáticamente en la siguiente corrida.

Uso:
  python scripts/recalibrar.py --campana 2026
  python scripts/recalibrar.py --campana 2026 --dry   # sin escribir
"""
import argparse
import io
import os
import sys
from datetime import date

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
from tchmotor import Supabase, JobRecalibracion  # noqa

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def _env(path, name):
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campana", default=str(date.today().year))
    ap.add_argument("--corrida", default=None, help="acotar a una fecha_corrida (def: todas)")
    ap.add_argument("--dry", action="store_true", help="calcula pero no escribe")
    args = ap.parse_args()

    os.environ.setdefault("TCH_SUPABASE_URL", _env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_URL"))
    os.environ.setdefault("TCH_SUPABASE_KEY", _env(r"C:\Users\Agr349\turnos-jornales\.env.local", "RIOMAP_SERVICE_ROLE_KEY"))

    sb = Supabase()
    job = JobRecalibracion(sb)
    hoy = date.today().isoformat()

    regs = job.emparejar(args.campana, args.corrida)
    print(f"cortes cerrados emparejados (modo motor): {len(regs)}")
    if not regs:
        print("nada que recalibrar aún — faltan cortes en tch_real o estimados que casen.")
        return

    filas = job.calcular(args.campana, args.corrida, vigente_desde=hoy)
    for f in filas:
        print(f"  {f['planta']}: factor {f['factor']}  "
              f"(sesgo crudo {f['sesgo_pct']:+.1f}%, MAPE reportado {f['mape']}%, "
              f"{f['n_suertes']} cortes, {f['area_ha']} ha)")

    if args.dry:
        print("\n[dry] no se escribió tch_factor.")
        return
    _, n = job.correr(args.campana, args.corrida, vigente_desde=hoy)
    print(f"\nescritas {n} filas en tch_factor (campaña {args.campana}).")


if __name__ == "__main__":
    main()
