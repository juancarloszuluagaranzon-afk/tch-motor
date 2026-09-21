# -*- coding: utf-8 -*-
"""Carga a tch_real (Rio Map) los cortes reales del módulo de Cosecha de campo
(app Turnos, tablas cosecha_cortes + cosecha_vagones). Es la fuente autoritativa:
trae la soca REAL (numero_corte) y el TCH calculado sobre el área efectiva, con la
misma fórmula del dominio (toneladas del mejor peso por vagón + caña sin vagones,
sobre área − área descontada).

A diferencia de cargar_reales_validacion (soca copiada del estimado), aquí la soca
es la del corte cosechado → el guard de soca de la recalibración funciona de verdad.

Uso:
  python scripts/cargar_reales_cosecha.py --mes 2026-09 --dry
  python scripts/cargar_reales_cosecha.py --mes 2026-09          # escribe tch_real
"""
import argparse, json, os, sys, urllib.request
sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")
import correr_estimados as ce
from tchmotor import Supabase

AGRO = r"C:\Users\Agr349\agrocontrol-campo\.env.local"
TURN = r"C:\Users\Agr349\turnos-jornales\.env.local"


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def turnos_get(tabla):
    url = ce._env(TURN, "NEXT_PUBLIC_SUPABASE_URL").rstrip("/")
    key = ce._env(TURN, "SUPABASE_SERVICE_ROLE_KEY")
    filas, off = [], 0
    while True:
        u = f"{url}/rest/v1/{tabla}?select=*&limit=1000&offset={off}"
        req = urllib.request.Request(u, headers={"apikey": key, "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            lote = json.loads(r.read().decode())
        filas.extend(lote)
        if len(lote) < 1000:
            break
        off += 1000
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", default="2026-09", help="YYYY-MM del cierre; 'todos' para todas las terminadas")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    cortes = turnos_get("cosecha_cortes")
    vagones = turnos_get("cosecha_vagones")
    vp = {}
    for v in vagones:
        vp.setdefault(v["corte_id"], []).append(v)

    def area_ef(c):
        a = num(c.get("area_ha"))
        if a is None:
            return None
        n = a - (num(c.get("area_descontada_ha")) or 0)
        return round(n, 2) if n > 0 else None

    def real_tch(c):
        vs = vp.get(c["id"], [])
        fuera = (num(c.get("ton_mes_anterior")) or 0) + (num(c.get("ton_sin_vagones")) or 0)
        ton = sum((num(v.get("peso_real_kg")) if num(v.get("peso_real_kg")) is not None
                   else (num(v.get("peso_estimado_kg")) or 0)) for v in vs) / 1000 + fuera
        ar = area_ef(c)
        return ton, ar, (ton / ar if ar and ar > 0 else None)

    filas = []
    for c in cortes:
        if c.get("estado") != "T":
            continue
        if args.mes != "todos" and str(c.get("fecha_fin") or "")[:7] != args.mes:
            continue
        ton, ar, tch = real_tch(c)
        if tch is None or ar is None:
            continue
        soca = num(c.get("numero_corte"))
        filas.append({
            "sec_ste": c["suerte"], "campana": "2026", "planta": "riopaila",
            "corte": int(soca) if soca is not None else None,
            "variedad": c.get("variedad"), "area_ha": ar,
            "tc_total": round(ton, 1), "tch_real": round(tch, 1),
            "fecha_corte_real": c.get("fecha_fin"), "fuente": "cosecha_2026",
        })
    print(f"reales de cosecha ({args.mes}): {len(filas)} filas")
    for f in filas[:5]:
        print("  ", {k: f[k] for k in ("sec_ste", "corte", "tch_real", "area_ha", "fecha_corte_real")})
    if args.dry:
        print("[dry] no se escribió tch_real.")
        return
    os.environ.setdefault("TCH_SUPABASE_URL", ce._env(AGRO, "NEXT_PUBLIC_SUPABASE_URL"))
    os.environ.setdefault("TCH_SUPABASE_KEY", ce._env(TURN, "RIOMAP_SERVICE_ROLE_KEY"))
    sb = Supabase()
    n = sb.guardar_reales(filas)
    print(f"escritas {n} filas en tch_real (fuente cosecha_2026, campaña 2026).")


if __name__ == "__main__":
    main()
