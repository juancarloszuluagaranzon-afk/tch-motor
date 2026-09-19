"""Puebla tch_estimado por TANDAS (resiliente).

A diferencia de correr_estimados (una sola escritura al final), este divide las
suertes en lotes y escribe cada lote apenas lo estima: el tablero se llena
progresivamente, un fallo de red no bota lo ya hecho, y hay progreso en vivo.

Uso:  python -u scripts/poblar.py --lote 40
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")

from tchmotor import Supabase, JobEstimados, curva_suerte, aforos_vigentes  # noqa
import correr_estimados as ce  # reusa cargar_suertes, _env, FACTORES  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lote", type=int, default=40, help="suertes por escritura")
    ap.add_argument("--edad-min", type=float, default=0)
    ap.add_argument("--edad-max", type=float, default=20)
    ap.add_argument("--n", type=int, default=0, help="límite total (0 = todas)")
    args = ap.parse_args()

    os.environ.setdefault("TCH_SUPABASE_URL", ce._env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_URL"))
    os.environ.setdefault("TCH_SUPABASE_KEY", ce._env(r"C:\Users\Agr349\turnos-jornales\.env.local", "RIOMAP_SERVICE_ROLE_KEY"))

    hoy = date.today()
    suertes = ce.cargar_suertes(args.edad_min, args.edad_max, hoy)
    if args.n:
        suertes = suertes[: args.n]
    print(f"suertes a estimar: {len(suertes)} (edad {args.edad_min}-{args.edad_max}), lote {args.lote}", flush=True)

    sb = Supabase()
    factores = dict(ce.FACTORES)
    try:
        aprendidos = sb.cargar_factores()
        if aprendidos:
            factores.update(aprendidos)
            print("factores aprendidos:", aprendidos, flush=True)
    except Exception:
        pass

    # aforos en vivo (tabla propia tch_aforo_vivo, cargada del libro de Agronomía
    # con scripts/cargar_aforos.py) — opcional; devuelve el promedio de los métodos
    aforos = {}
    try:
        aforos = aforos_vigentes(sb, hoy.isoformat())  # tabla tch_aforo_vivo (mismo Supabase)
        print(f"aforos en vivo: {len(aforos)} suertes", flush=True)
    except Exception as e:
        print("aviso aforos:", str(e)[:100], flush=True)

    job = JobEstimados(sb, curva_suerte)
    print("entrenando el motor...", flush=True)
    job.entrenar()

    total, con_curva, fus, errores = len(suertes), 0, 0, 0
    for i in range(0, total, args.lote):
        lote = suertes[i:i + args.lote]
        try:
            filas = job.estimar(lote, hoy.isoformat(), factores=factores, aforos=aforos)
            n = sb.guardar_estimados(filas) if filas else 0
            con_curva += len(filas)
            fus += sum(1 for f in filas if f["modo"] == "fusion")
            print(f"  [{min(i + args.lote, total)}/{total}] lote de {len(lote)} → "
                  f"{len(filas)} con curva, escritas (acum {con_curva}, fusión {fus})", flush=True)
        except Exception as e:
            errores += 1
            print(f"  [{min(i + args.lote, total)}/{total}] ERROR en lote: {str(e)[:140]}", flush=True)

    print(f"\nlisto: {con_curva}/{total} suertes con estimado en tch_estimado "
          f"({fus} con fusión de aforo, {errores} lotes con error).", flush=True)


if __name__ == "__main__":
    main()
