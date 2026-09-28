# -*- coding: utf-8 -*-
"""Prueba de equivalencia: Earth Engine contra las curvas de Copernicus/Rio Map ya guardadas.

Recalcula en Earth Engine, con la misma receta de Rio Map (ventanas de 30 días desde el corte,
mosaico más reciente, máscara SCL, 10 m), las curvas de una muestra de los ciclos de
data/dataset_entrenamiento.jsonl y compara ventana por ventana (NDVI, NDMI, EVI).

Uso:  .venv-gee\\Scripts\\python.exe scripts\\gee_paridad.py [--n 120]
Salida: data/gee/paridad_pares.csv y un resumen en pantalla.
"""
import argparse
import collections
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from tchmotor import gee  # noqa: E402

RAIZ = gee.RAIZ
DS = os.path.join(RAIZ, "data", "dataset_entrenamiento.jsonl")
OUT = os.path.join(RAIZ, "data", "gee")
IDX = ["NDVI", "NDMI", "EVI"]


def muestra(filas, n):
    """Muestra estratificada por planta y año de cosecha."""
    grupos = collections.defaultdict(list)
    for r in filas:
        grupos[(r["planta"], r["anio"])].append(r)
    por_grupo = max(1, n // len(grupos))
    out = []
    for k in sorted(grupos):
        g = sorted(grupos[k], key=lambda r: r["key"])
        paso = max(1, len(g) // por_grupo)
        out.extend(g[::paso][:por_grupo])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120, help="ciclos a comparar (0 = todos)")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    filas = [json.loads(l) for l in open(DS, encoding="utf-8")]
    sel = filas if a.n == 0 else muestra(filas, a.n)
    proyecto, _ = gee.iniciar()
    print(f"Proyecto {proyecto}: comparando {len(sel)} ciclos")
    pares, fallos = [], 0
    t0 = time.time()
    for i, r in enumerate(sel, 1):
        pol = gee.coords_tablon(r["tab_id"], r["planta"])
        if not pol:
            fallos += 1
            continue
        try:
            serie = gee.serie_ventanas(pol, r["cut"], r["harvest"])
        except Exception as e:
            fallos += 1
            print(f"  {r['key']}: error {str(e)[:120]}")
            continue
        g = {p["from"]: p for p in serie}
        for idx in IDX:
            for pt in r["curves"].get(idx, []):
                f = pt["from"][:10]
                ge = g.get(f, {}).get(idx)
                pares.append({"key": r["key"], "planta": r["planta"], "anio": r["anio"], "indice": idx, "from": f,
                              "copernicus": pt.get("mean"), "gee": ge, "pixeles_gee": g.get(f, {}).get("pixeles")})
        if i % 10 == 0:
            print(f"  {i}/{len(sel)} ciclos · {time.time() - t0:.0f} s")
    df = pd.DataFrame(pares)
    df.to_csv(os.path.join(OUT, "paridad_pares.csv"), index=False)
    print(f"\nCiclos sin geometría o con error: {fallos}")
    print(f"{'índice':<6} {'ventanas':>8} {'ambos':>6} {'solo Cop.':>9} {'solo GEE':>8} {'r':>6} {'sesgo':>7} {'MAE':>6}")
    for idx in IDX:
        d = df[df.indice == idx]
        both = d.dropna(subset=["copernicus", "gee"])
        solo_c = d["copernicus"].notna() & d["gee"].isna()
        solo_g = d["copernicus"].isna() & d["gee"].notna()
        r = np.corrcoef(both.copernicus, both.gee)[0, 1] if len(both) > 2 else float("nan")
        sesgo = (both.gee - both.copernicus).mean()
        mae = (both.gee - both.copernicus).abs().mean()
        print(f"{idx:<6} {len(d):>8} {len(both):>6} {solo_c.sum():>9} {solo_g.sum():>8} {r:>6.3f} {sesgo:>+7.3f} {mae:>6.3f}")
    print("\nCriterio: r >= 0,90 y sesgo pequeño (|sesgo| < 0,03) => Earth Engine puede reemplazar a Copernicus en el modelo.")


if __name__ == "__main__":
    main()
