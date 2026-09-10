"""Agronomía: zona agroecológica de Cenicaña y catálogo de variedades.

- La zona se codifica `[grupo de suelo]H[grupo de humedad 0-5]` (p. ej. `6H1`).
  El grupo de humedad H0..H5 va de seco (déficit) a húmedo (exceso).
- El ZQM histórico nombra las variedades con códigos internos `V##`; el maestro
  y la base de aforos usan el nombre Cenicaña `CC ##-####`. `map_variedad`
  traduce del código al nombre para que el join funcione en todo el pipeline.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

_ZONA = re.compile(r"^(\d{1,2})H([0-5])$")

_DATA = Path(__file__).resolve().parent.parent / "data"


def parse_zona(codigo: str | None) -> tuple[float | None, float | None]:
    """(grupo_suelo, grupo_humedad) desde el código; (None, None) si no aplica."""
    if not codigo:
        return None, None
    m = _ZONA.match(str(codigo).strip())
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def cargar_var_map(path: str | Path | None = None) -> dict[str, str]:
    """Diccionario V## → nombre Cenicaña (data/var_map.json)."""
    p = Path(path) if path else _DATA / "var_map.json"
    return json.loads(p.read_text(encoding="utf-8"))


def map_variedad(codigo: str | None, var_map: dict[str, str]) -> str | None:
    """Traduce V## → CC ##-####; deja igual lo que no esté en el mapa."""
    if codigo is None:
        return None
    return var_map.get(str(codigo).strip(), str(codigo).strip())
