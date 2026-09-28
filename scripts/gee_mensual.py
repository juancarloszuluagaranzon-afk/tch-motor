# -*- coding: utf-8 -*-
"""Tabla mensual de índices por suerte (Riopaila y Castilla) con Google Earth Engine.

Para cada mes calendario, la media por suerte de NDVI, NDMI, EVI, NDRE, SAVI, GNDVI (Sentinel-2 con
máscara SCL, mediana del mes) y VV, VH, RVI (Sentinel-1), más la fracción despejada. Sirve para ver
en qué mes del ciclo se separó 2026 de los años anteriores y para reentrenar el modelo.

Uso:  .venv-gee\\Scripts\\python.exe scripts\\gee_mensual.py --desde 2018-06 --hasta 2026-09 [--planta riopaila]
      [--rehacer-desde 2026-08]   (vuelve a extraer desde ese mes, p. ej. el último que quedó incompleto)
Salida: data/gee/mensual_<planta>.csv (reanuda: salta los meses ya guardados).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tchmotor import gee  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2018-06")
    ap.add_argument("--hasta", default="2026-09")
    ap.add_argument("--planta", choices=["riopaila", "castilla", "ambas"], default="ambas")
    ap.add_argument("--rehacer-desde", default=None)
    ap.add_argument("--sin-radar", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(gee.RUTA_MENSUAL), exist_ok=True)
    proyecto, _ = gee.iniciar()
    for planta in (["riopaila", "castilla"] if a.planta == "ambas" else [a.planta]):
        print(f"{planta} · proyecto {proyecto}", flush=True)
        n = gee.actualizar_tabla_mensual(planta, a.desde, a.hasta, a.rehacer_desde, radar=not a.sin_radar,
                                         log=lambda s: print(s, flush=True))
        print(f"{planta}: {n} meses nuevos", flush=True)


if __name__ == "__main__":
    main()
