"""Configuración de la app: dónde están los insumos, la carpeta de trabajo y las llaves.

- `config.json` (en %APPDATA%\\EstimadorTCH) guarda lo que no es secreto: carpetas, proyecto de Earth Engine,
  datos de publicación.
- `llaves.dat`, al lado, guarda los secretos cifrados con DPAPI (solo este usuario de Windows en este PC
  los puede leer): la llave JSON de Earth Engine, la llave de la app de Turnos y el token de Vercel.
- La carpeta de trabajo (conviene que sea compartida, p. ej. en OneDrive) guarda lo que la corrida
  escribe: la tabla del satélite, los datos del tablero con su historial y los registros.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from . import dpapi

APP_DIR = Path(os.environ.get("ESTIMADORTCH_DATOS") or Path(os.environ.get("APPDATA", Path.home())) / "EstimadorTCH")
CONFIG = APP_DIR / "config.json"
LLAVES = APP_DIR / "llaves.dat"
SECRETOS = ("gee_llave_json", "turnos_key", "vercel_token")


def congelado() -> bool:
    return getattr(sys, "frozen", False)


def base() -> Path:
    """Carpeta con los recursos empaquetados (en el instalado, la carpeta _internal)."""
    if congelado():
        return Path(sys._MEIPASS)  # noqa: SLF001
    return Path(__file__).resolve().parent.parent  # producto/


def recursos() -> Path:
    return base() / "recursos"


def ui_dir() -> Path:
    return (base() / "app" / "ui") if not congelado() else base() / "ui"


def _publicacion_empaquetada() -> dict:
    p = recursos() / "publicacion.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def defectos() -> dict:
    pub = _publicacion_empaquetada()
    docs = Path.home() / "Documents"
    return {
        "carpeta_insumos": str(docs / "RIOPAILA AGRICOLA"),
        "carpeta_trabajo": str(docs / "Estimador TCH"),
        "gee_proyecto": "riopaila-estimador-tch",
        "turnos_url": pub.get("turnos_url", ""),
        "vercel_equipo": pub.get("vercel_equipo", ""),
        "vercel_proyecto": pub.get("vercel_proyecto", ""),
        "vercel_nombre": pub.get("vercel_nombre", "tch-dashboard"),
        "alias": pub.get("alias", "estimador-tch.vercel.app"),
    }


def cargar() -> dict:
    cfg = defectos()
    if CONFIG.exists():
        cfg.update({k: v for k, v in json.loads(CONFIG.read_text(encoding="utf-8")).items() if v not in (None, "")})
    return cfg


def guardar(cambios: dict) -> dict:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    actual = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    actual.update({k: v for k, v in cambios.items() if k not in SECRETOS})
    CONFIG.write_text(json.dumps(actual, ensure_ascii=False, indent=1), encoding="utf-8")
    return cargar()


def llaves() -> dict:
    if not LLAVES.exists():
        return {}
    return json.loads(dpapi.descifrar(LLAVES.read_bytes()).decode("utf-8"))


def guardar_llaves(cambios: dict) -> None:
    """Solo actualiza las que vienen con valor; "" deja la anterior y None la borra."""
    actual = llaves()
    for k in SECRETOS:
        if k in cambios and cambios[k] is None:
            actual.pop(k, None)
        elif cambios.get(k):
            actual[k] = cambios[k]
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LLAVES.write_bytes(dpapi.cifrar(json.dumps(actual).encode("utf-8")))


# ---------------------------------------------------------------- carpetas de trabajo
def trabajo(cfg: dict) -> Path:
    return Path(cfg["carpeta_trabajo"])


def tablero_data(cfg: dict) -> Path:
    return trabajo(cfg) / "Tablero" / "data"


def satelite(cfg: dict) -> Path:
    return trabajo(cfg) / "Satelite"


def registros(cfg: dict) -> Path:
    return trabajo(cfg) / "Registros"


def preparar_trabajo(cfg: dict) -> list[str]:
    """Crea la carpeta de trabajo y, si está vacía, la siembra con la tabla del satélite y los datos del
    tablero que trae el instalador. Nunca pisa lo que ya exista. Devuelve lo que copió."""
    copiado = []
    ini = recursos() / "inicial"
    for origen, destino in ((ini / "satelite", satelite(cfg)), (ini / "tablero_data", tablero_data(cfg))):
        destino.mkdir(parents=True, exist_ok=True)
        if not origen.exists():
            continue
        for f in origen.rglob("*"):
            d = destino / f.relative_to(origen)
            if f.is_dir():
                d.mkdir(parents=True, exist_ok=True)
            elif not d.exists():
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, d)
                copiado.append(str(d.relative_to(trabajo(cfg))))
    registros(cfg).mkdir(parents=True, exist_ok=True)
    return copiado


def entorno(cfg: dict | None = None) -> dict:
    """Variables de entorno con las que corren las tareas (el motor lee sus rutas y llaves de aquí)."""
    cfg = cfg or cargar()
    k = llaves()
    env = dict(os.environ)
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "TCH_DOCS": cfg["carpeta_insumos"],
        "TCH_TABLERO": str(tablero_data(cfg)),
        "TCH_GEE_DIR": str(satelite(cfg)),
        "TCH_TABLONES": str(recursos() / "tablones"),
        "TCH_MAESTRO_LOCAL": str(recursos() / "maestro.csv"),
        "GEE_PROJECT": cfg.get("gee_proyecto", ""),
    })
    if k.get("gee_llave_json"):
        env["GEE_KEY_JSON"] = k["gee_llave_json"]
    if cfg.get("turnos_url") and k.get("turnos_key"):
        env["TCH_TURNOS_URL"], env["TCH_TURNOS_KEY"] = cfg["turnos_url"], k["turnos_key"]
    return env


def resumen(cfg: dict) -> dict:
    """Lo que la pantalla de configuración puede mostrar: sin secretos, solo si están puestos."""
    k = llaves()
    llave_gee = None
    if k.get("gee_llave_json"):
        try:
            llave_gee = json.loads(k["gee_llave_json"]).get("client_email")
        except ValueError:
            llave_gee = "llave guardada"
    return {**cfg, "tiene": {s: bool(k.get(s)) for s in SECRETOS}, "cuenta_gee": llave_gee}
