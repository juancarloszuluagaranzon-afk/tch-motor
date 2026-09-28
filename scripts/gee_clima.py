# -*- coding: utf-8 -*-
"""Clima mensual por suerte (Riopaila y Castilla) con ERA5-Land en Earth Engine.

tmax y tmin medias (°C), lluvia (mm) y humedad relativa media (%) de cada mes, en el centroide
de cada suerte. Sirve para los rasgos de calor al final del ciclo y de humedad del arranque.

Uso:  .venv-gee\\Scripts\\python.exe scripts\\gee_clima.py [--desde 2010] [--hasta 2026]
Salida: data/gee/clima_mensual.csv (reanuda: rehace solo el último año guardado y los que falten).
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd  # noqa: E402
from tchmotor import gee  # noqa: E402

DESTINO = os.path.join(gee.RAIZ, "data", "gee", "clima_mensual.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2010)
    ap.add_argument("--hasta", type=int, default=2026)
    a = ap.parse_args()
    gee.iniciar()
    ultimo = gee.ultimo_dia_clima()
    print(f"ERA5-Land publicado hasta {ultimo}", flush=True)
    prev = pd.read_csv(DESTINO) if os.path.exists(DESTINO) else pd.DataFrame()
    hechos = set(prev.anio.unique()) if len(prev) else set()
    if hechos:  # el último año guardado pudo quedar incompleto: se rehace
        hechos.discard(max(hechos))
        prev = prev[prev.anio.isin(hechos)]
    partes = [prev] if len(prev) else []
    for planta in ["riopaila", "castilla"]:
        cen = gee.centroides_suertes(planta)
        print(f"{planta}: {len(cen)} suertes", flush=True)
        for anio in range(a.desde, a.hasta + 1):
            if anio in hechos:
                continue
            t0 = time.time()
            for intento in range(3):
                try:
                    filas = gee.tabla_clima_anual(cen, anio, hasta=ultimo)
                    break
                except Exception as e:
                    print(f"  {anio} intento {intento + 1} falló: {str(e)[:120]}", flush=True)
                    time.sleep(10 * (intento + 1))
            else:
                continue
            df = pd.DataFrame(filas)
            df["planta"] = planta
            partes.append(df)
            print(f"  {anio}: {len(df)} filas · {time.time() - t0:.0f} s", flush=True)
    out = pd.concat(partes, ignore_index=True)
    out = out.drop_duplicates(["planta", "sec_ste", "anio", "mes"], keep="last").sort_values(
        ["planta", "sec_ste", "anio", "mes"])
    out.to_csv(DESTINO, index=False)
    print(f"guardado {DESTINO}: {len(out)} filas", flush=True)


if __name__ == "__main__":
    main()
