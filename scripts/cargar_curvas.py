# -*- coding: utf-8 -*-
"""Rellena tch_curva con las curvas de desarrollo de los ciclos que tienen serie
satelital guardada en data/dataset_entrenamiento.jsonl (503 ciclos históricos,
sin satélite). tch_inst = TCH_ciclo · EVI(edad)/EVI_pico (interpretación A).

Requisito: aplicar sql/0004_tch_curva.sql en el SQL Editor de Rio Map.
Uso: python scripts/cargar_curvas.py [--dry]
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


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true"); args = ap.parse_args()
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
        evi_vals = [x["EVI"] for x in by_f.values() if "EVI" in x]
        evi_pico = max(evi_vals) if evi_vals else None
        if not evi_pico or evi_pico <= 0:
            continue
        for f, ix in sorted(by_f.items()):
            edad = round((f - cut).days / 30.44, 1)
            if edad < 0 or edad > 16:
                continue
            evi = ix.get("EVI")
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
    print(f"puntos de curva: {len(filas)} | ciclos (suerte×campaña): {ciclos}")
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
