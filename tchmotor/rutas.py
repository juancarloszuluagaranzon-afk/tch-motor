"""Rutas de los archivos de entrada y salida del motor, en un solo sitio.

Por defecto salen de la carpeta del usuario (`Path.home()`), así que en otro PC con la misma
organización de carpetas no hay que cambiar nada. Si allá están en otra parte, se ajustan con
variables de entorno o en `tch-motor/.env.local` (mismo formato `CLAVE=valor` que GEE_PROJECT):

  TCH_DOCS             carpeta «RIOPAILA AGRICOLA» con las subcarpetas 01 Estimados y TCH / 02 Cosecha y molienda
  TCH_TABLONES         carpeta con tablones_<planta>.geojson (repo agrocontrol-campo, public/data)
  TCH_TABLERO          carpeta data/ del tablero (repo tch-dashboard), donde escribe la corrida mensual
  TCH_MAESTRO_LOCAL    maestro.csv local (repo maestro-riopaila), respaldo si no hay internet
  TCH_TURNOS_ENV       .env.local de la app de Turnos (para leer las cosechas de la app)
  TCH_AFOROS_DIAMETRO  libro «Aforos con Diámetro» de Agronomía
  TCH_PPTO_REFERENCIA  presupuesto de cosecha de Planeación (JSON de la app de Turnos), referencia del presupuesto
  TCH_GEE_DIR          carpeta de las tablas de Earth Engine (por defecto data/gee del repo; la app empaquetada
                       la pone en su carpeta de trabajo, que sí se puede escribir)
"""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENV_LOCAL = RAIZ / ".env.local"
HOME = Path.home()


def env(clave: str, defecto: str | Path | None = None) -> str | None:
    """Variable de entorno o línea `CLAVE=valor` de tch-motor/.env.local."""
    v = os.environ.get(clave)
    if v:
        return v.strip()
    if ENV_LOCAL.exists():
        for linea in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea.startswith(clave + "="):
                return linea.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None if defecto is None else str(defecto)


def ruta(clave: str, defecto: Path) -> Path:
    return Path(env(clave, defecto))


DOCS = ruta("TCH_DOCS", HOME / "Documents" / "RIOPAILA AGRICOLA")
ESTIMADOS_DIR = DOCS / "01 Estimados y TCH"
COSECHA_DIR = DOCS / "02 Cosecha y molienda"

ZQM_HIST = COSECHA_DIR / "historico zqm.xlsx"
ZQM_2026 = COSECHA_DIR / "zqm 26.xlsx"
COSECHAS_RECIENTES = COSECHA_DIR / "cosechas_recientes.xlsx"
BASE_AFOROS = ESTIMADOS_DIR / "Base de aforos completa 2026.xlsx"

TABLONES_DIR = ruta("TCH_TABLONES", HOME / "agrocontrol-campo" / "public" / "data")
TABLERO_DATA = ruta("TCH_TABLERO", HOME / "tch-dashboard" / "data")
MAESTRO_LOCAL = ruta("TCH_MAESTRO_LOCAL", HOME / "maestro-riopaila" / "maestro.csv")
TURNOS_ENV = ruta("TCH_TURNOS_ENV", HOME / "turnos-jornales" / ".env.local")
AFOROS_DIAMETRO = ruta("TCH_AFOROS_DIAMETRO", HOME / "OneDrive - Riopaila Agricola - Castilla Agricola"
                       / "Agronomía-Alejandra Bran" / "(AFOROS)-PRONOSTICOS" / "Aforos 2026" / "Aforos con Diámetro 2026.xlsx")
PPTO_REFERENCIA = ruta("TCH_PPTO_REFERENCIA", HOME / "turnos-jornales" / "data" / "presupuesto_cosecha.json")

# tablas de Earth Engine (comprimidas, van en git para que otro PC entrene sin volver a extraer)
GEE_DIR = ruta("TCH_GEE_DIR", RAIZ / "data" / "gee")
MENSUAL = str(GEE_DIR / "mensual_{planta}.csv.gz")
CLIMA = GEE_DIR / "clima_mensual.csv.gz"
