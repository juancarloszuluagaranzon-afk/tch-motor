"""Job mensual de estimados (P2).

Lee el maestro de Rio Map (JSON estático de agrocontrol-campo) + el índice de
tablones, arma las suertes activas, y corre el motor: extrae curvas (endpoint
Rio Map) → features → predice → recalibra → escribe en tch_estimado (Supabase
Rio Map).

Credenciales del entorno (TCH_SUPABASE_URL, TCH_SUPABASE_KEY). Uso:
  python scripts/correr_estimados.py --n 8 --edad-min 11 --edad-max 13
"""
import argparse
import io
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
from tchmotor import Supabase, JobEstimados, curva_suerte, aforos_vigentes  # noqa

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

RIOMAP_DATA = r"C:\Users\Agr349\agrocontrol-campo\public\data"
TABLONES_IDX = r"C:\Users\Agr349\tch-motor\data\tablones_index.json"
FACTORES = {"riopaila": 0.981, "castilla": 0.914}  # recalibración por planta (P5 la derivará sola)
_DIAS_MES = 30.44


def _env(path, name):
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _iso(s):
    try:
        date.fromisoformat(str(s)[:10])
        return str(s)[:10]
    except Exception:
        return None


def cargar_suertes(edad_min, edad_max, hoy):
    idx = json.load(open(TABLONES_IDX, encoding="utf-8"))
    suertes = []
    for fn in ("maestro_suertes.json", "maestro_castilla.json"):
        m = json.load(open(os.path.join(RIOMAP_DATA, fn), encoding="utf-8"))
        for sec, v in m.items():
            if sec not in idx:
                continue
            if (v.get("uso") or "").strip().upper() not in ("CAÑA", "CANA"):
                continue
            edad = v.get("edad_csv")
            var = v.get("variedad")
            if edad is None or not (edad_min <= edad <= edad_max) or var in (None, "RENOVACION", "VARIAS"):
                continue
            tab_id, _ha, planta = idx[sec]
            cut = (hoy - timedelta(days=float(edad) * _DIAS_MES)).isoformat()
            suertes.append({
                "sec_ste": sec, "planta": planta, "tab_id": tab_id,
                "cut": cut, "harvest": hoy.isoformat(),
                "edad": round(float(edad), 1), "corte": v.get("numero_corte"),
                "variedad": var, "zona_agro": v.get("zona_agroecologica"),
                "ha": v.get("area_neta_ha"), "area": v.get("area_neta_ha"),
                "fecha_corte_prevista": _iso(v.get("fecha_proximo_corte")),
            })
    return suertes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="límite de suertes (0 = todas)")
    ap.add_argument("--edad-min", type=float, default=0)
    ap.add_argument("--edad-max", type=float, default=20)
    args = ap.parse_args()

    os.environ.setdefault("TCH_SUPABASE_URL", _env(r"C:\Users\Agr349\agrocontrol-campo\.env.local", "NEXT_PUBLIC_SUPABASE_URL"))
    os.environ.setdefault("TCH_SUPABASE_KEY", _env(r"C:\Users\Agr349\turnos-jornales\.env.local", "RIOMAP_SERVICE_ROLE_KEY"))

    hoy = date.today()
    suertes = cargar_suertes(args.edad_min, args.edad_max, hoy)
    if args.n:
        suertes = suertes[: args.n]
    print(f"suertes a estimar: {len(suertes)} (edad {args.edad_min}-{args.edad_max})")

    sb = Supabase()  # Rio Map (escribe estimados)
    # Factor de recalibración: el aprendido (P5, tch_factor) manda sobre el fijo.
    factores = dict(FACTORES)
    try:
        aprendidos = sb.cargar_factores()
        if aprendidos:
            factores.update(aprendidos)
            print("factores aprendidos (tch_factor):", aprendidos)
    except Exception as e:
        print("aviso: sin factores aprendidos, uso los fijos:", str(e)[:100])
    # Aforos en vivo desde el Supabase de Turnos & Jornales (proyecto aparte).
    aforos = {}
    turl = _env(r"C:\Users\Agr349\turnos-jornales\.env.local", "NEXT_PUBLIC_SUPABASE_URL")
    tkey = _env(r"C:\Users\Agr349\turnos-jornales\.env.local", "SUPABASE_SERVICE_ROLE_KEY")
    if turl and tkey:
        try:
            aforos = aforos_vigentes(Supabase(url=turl, key=tkey), hoy.isoformat())
            print(f"aforos en vivo (Turnos): {len(aforos)} suertes")
        except Exception as e:
            print("aviso: no se pudieron leer aforos en vivo:", str(e)[:120])

    job = JobEstimados(sb, curva_suerte)
    print("entrenando el motor con el histórico...")
    job.entrenar()
    print("extrayendo curvas y estimando...")
    filas, n = job.correr(suertes, hoy.isoformat(), factores=factores, aforos=aforos)
    nf = sum(1 for f in filas if f["modo"] == "fusion")
    print(f"\nescritas {n} filas en tch_estimado (corrida {hoy}) — {nf} con fusión de aforo")
    for f in filas[:12]:
        print(f"  {f['sec_ste']} soca {f['soca']} {f['variedad']}: "
              f"TCH {f['tch_estimado']} ± {f['tch_std']}  ({f['ton_estimadas']} t) [{f['modo']}]")


if __name__ == "__main__":
    main()
