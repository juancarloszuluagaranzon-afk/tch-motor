# -*- coding: utf-8 -*-
"""TCH real frente al motor para las cosechas de un mes que están en cosechas_recientes.xlsx (cualquier planta).

Sirve para Castilla, que no está en la app de Cosecha: su real llega como lista (suerte, TCH, fecha) y se agrega
al Excel con `cosechas_desde_app.py --lista`. Para Riopaila es más exacto `comparar_real_motor_aforo.py`, que lee
el área y las toneladas del corte en la app.

Motor: el estimado vigente ANTES del cierre: la corrida más reciente del historial del tablero anterior a la fecha
en que terminó el corte (una suerte solo aparece en una corrida mientras está en pie con 4 meses o más, así que ese
estimado es el del ciclo que se cosechó). Agregados ponderados por el área neta del maestro.

Uso:  .venv-gee\\Scripts\\python.exe scripts\\comparar_real_motor_recientes.py --planta castilla --mes 2026-10 [--json x.json]
"""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openpyxl  # noqa: E402
import pandas as pd  # noqa: E402

from tchmotor import rutas  # noqa: E402
from presupuesto_cosecha import leer_maestro  # noqa: E402

PREFIJO = {"riopaila": "3", "castilla": "2"}  # sector 3xxx Riopaila, 2xxx Castilla


def armar(planta, mes):
    wb = openpyxl.load_workbook(rutas.COSECHAS_RECIENTES, read_only=True)
    filas = []
    for r in wb["Cosechas"].iter_rows(min_row=2, values_only=True):
        if not r or not r[0] or r[1] is None or r[2] is None:
            continue
        s, f = str(r[0]).strip(), (r[2].date() if hasattr(r[2], "date") else r[2])
        if s.startswith(PREFIJO[planta]) and isinstance(f, date) and f.strftime("%Y-%m") == mes:
            filas.append((s, float(r[1]), f))
    ma, _ = leer_maestro(planta)
    hist = {}
    for p in sorted((rutas.TABLERO_DATA / "historial").glob("estimados_*.json")):
        hist[p.stem.split("_", 1)[1]] = {e["sec_ste"]: e for e in json.load(open(p, encoding="utf-8")) if e["planta"] == planta}
    out = []
    for s, real, f in filas:
        e, fuente = None, None
        for d in sorted(hist, reverse=True):
            if d < f.isoformat() and s in hist[d]:
                e, fuente = hist[d][s], f"Corrida {d}"
                break
        v = ma.get(s, {})
        out.append(dict(sec_ste=s, hacienda=v.get("finca"), fecha=f, real=real, area=v.get("area"),
                        motor=None if e is None else float(e["tch_estimado"]), soca=None if e is None else int(e["soca"]),
                        variedad=(e or {}).get("variedad") or v.get("var"), fuente=fuente,
                        en_maestro=bool(v)))
    return pd.DataFrame(out).sort_values(["fecha", "sec_ste"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planta", choices=list(PREFIJO), default="castilla")
    ap.add_argument("--mes", required=True, help="AAAA-MM de la fecha en que terminó el corte")
    ap.add_argument("--json", default=None, help="guarda el detalle por suerte (para gráficas)")
    a = ap.parse_args()
    d = armar(a.planta, a.mes)
    m = d[d.motor.notna() & d.area.notna()].copy()
    m["err"] = m.motor / m.real - 1
    w = lambda g, c: (g[c] * g.area).sum() / g.area.sum()  # noqa: E731
    print(f"{a.planta} {a.mes}: {len(d)} cosechas · con motor y área {len(m)} · {m.area.sum():.1f} ha")
    if len(m):
        print(f"  real {w(m, 'real'):.1f} · motor {w(m, 'motor'):.1f} · desvío {w(m, 'motor') / w(m, 'real') - 1:+.1%} · "
              f"error por suerte {m.err.abs().mean():.1%} · dentro ±10 % {int((m.err.abs() <= 0.1).sum())} de {len(m)}")
        for nom, lo, hi in (("Plantilla", 1, 1), ("Soca 2-3", 2, 3), ("Soca 4-6", 4, 6), ("Soca 7-10", 7, 10), ("Soca 11+", 11, 99)):
            g = m[m.soca.between(lo, hi)]
            if len(g):
                print(f"  {nom:10s} n={len(g):2d} real {w(g, 'real'):6.1f} motor {w(g, 'motor'):6.1f} ({w(g, 'motor') / w(g, 'real') - 1:+.1%})")
        for nom, g in sorted(m.groupby("hacienda"), key=lambda kv: -kv[1].area.sum()):
            if len(g) >= 2:
                print(f"  {str(nom)[:16]:16s} n={len(g):2d} real {w(g, 'real'):6.1f} motor {w(g, 'motor'):6.1f} ({w(g, 'motor') / w(g, 'real') - 1:+.1%})")
    for x in d.itertuples():
        txt = "sin estimado" if x.motor != x.motor else f"motor {x.motor:6.1f} ({x.motor / x.real - 1:+.0%})"
        print(f"  {x.sec_ste} {str(x.hacienda)[:14]:14s} {x.fecha:%d-%m} real {x.real:6.1f} · {txt}"
              f"{'' if x.en_maestro else ' · no está en el maestro'}")
    if a.json:
        d.assign(fecha=d.fecha.astype(str)).to_json(a.json, orient="records", force_ascii=False, indent=1)
        print("detalle:", a.json)


if __name__ == "__main__":
    main()
