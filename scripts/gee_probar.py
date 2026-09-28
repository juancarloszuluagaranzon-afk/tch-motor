# -*- coding: utf-8 -*-
"""Prueba de conexión con Google Earth Engine: inicia la cuenta de servicio y hace un cálculo mínimo.

Uso (con el entorno aislado):  .venv-gee\\Scripts\\python.exe scripts\\gee_probar.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ee  # noqa: E402
from tchmotor import gee  # noqa: E402

try:
    proyecto, correo = gee.iniciar()
except Exception as e:  # sin imprimir detalles de la llave
    print("No se pudo iniciar Earth Engine:", str(e).split("\n")[0][:200])
    sys.exit(1)
print(f"Conectado al proyecto {proyecto} con la cuenta de servicio {correo}")

pol = gee.coords_tablon("3109-210-T1", "riopaila") or next(iter(gee.coords_suertes("riopaila").values()))
geom = gee.geom_ee(pol)
n = ee.ImageCollection(gee.S2).filterBounds(geom).filterDate("2026-01-01", "2026-09-01").size().getInfo()
serie = gee.serie_ventanas(pol, "2026-01-01", "2026-04-01")
print(f"Imágenes Sentinel-2 sobre la suerte de prueba, ene-ago 2026: {n}")
for p in serie:
    print(f"  {p['from']}  NDVI={p.get('NDVI')}  escenas={p.get('escenas')}  píxeles={p.get('pixeles')}")
print("Earth Engine responde. Siguiente paso: scripts\\gee_paridad.py")
