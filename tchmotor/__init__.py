"""Motor de estimados de TCH — Riopaila.

Núcleo reutilizable: features de la curva satelital + agronomía (variedad, zona
Cenicaña) + aforo sintético + aforo en vivo, un modelo Random Forest
edad-consciente y la recalibración por planta/campaña.
"""
from .aforo import (
    DENSIDAD_CANA,
    AforoSinteticoTabla,
    peso_por_diametro,
    tch_por_pesos,
    tch_por_diametro,
    AforoSintetico,
)
from .agronomia import parse_zona, cargar_var_map, map_variedad
from .curva import curve_pairs, curve_features
from .extraccion import (
    RIOMAP_ENDPOINT,
    build_url,
    parse_series,
    serie_indice,
    curva_suerte,
)
from .features import build_features, INDICES
from .modelo import MotorTCH
from .persistencia import Supabase
from .fusion import Fusion
from .aforo_vivo import aforos_vigentes
from .pipeline import JobEstimados
from .recalibracion import factor, aplicar, diagnosticos, por_planta
from .autocorreccion import JobRecalibracion

__all__ = [
    "DENSIDAD_CANA",
    "peso_por_diametro",
    "tch_por_pesos",
    "tch_por_diametro",
    "AforoSintetico",
    "parse_zona",
    "cargar_var_map",
    "map_variedad",
    "curve_pairs",
    "curve_features",
    "RIOMAP_ENDPOINT",
    "build_url",
    "parse_series",
    "serie_indice",
    "curva_suerte",
    "build_features",
    "INDICES",
    "MotorTCH",
    "Supabase",
    "AforoSinteticoTabla",
    "JobEstimados",
    "Fusion",
    "aforos_vigentes",
    "factor",
    "aplicar",
    "diagnosticos",
    "por_planta",
    "JobRecalibracion",
]
