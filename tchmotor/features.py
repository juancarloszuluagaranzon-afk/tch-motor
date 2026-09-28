"""Ensamblado del vector de features de una suerte, desde un registro crudo.

Un `registro` trae: curves (series por índice), cut (inicio de ciclo), variedad
(código V## del ZQM o nombre CC), corte (soca), zona_agro, edad, mes, ha.
Combina curva satelital + agronomía (variedad mapeada, zona→suelo/humedad) +
aforo sintético (siempre) + aforo en vivo (si existe). `max_age` trunca la curva
para proyectar caña joven.
"""
from __future__ import annotations
from .agronomia import parse_zona, map_variedad
from .aforo import AforoSintetico
from .curva import curve_pairs, curve_features

INDICES = ("NDVI", "NDMI", "EVI")


def build_features(
    registro: dict,
    sintetico: AforoSintetico,
    var_map: dict,
    aforo_vivo: float | None = None,
    max_age: float | None = None,
    indices: tuple = INDICES,
) -> dict:
    """Dict de features de una suerte (listo para el modelo).

    `indices` permite resumir más curvas (p. ej. NDRE de Earth Engine) sin cambiar
    el vector del motor actual, que usa NDVI/NDMI/EVI.
    """
    variedad = map_variedad(registro.get("variedad"), var_map)
    soca = registro.get("corte")
    sg, hum = parse_zona(registro.get("zona_agro"))
    s = sintetico.lookup(variedad, soca)

    f: dict = {
        "corte": soca,
        "edad": registro.get("edad"),
        "mes": registro.get("mes"),
        "ha": registro.get("ha"),
        "soilgrp": sg,
        "humedad": hum,
        "variedad": variedad,
        "hist_pob": s["pob"],
        "hist_peso": s["peso"],
        "hist_dia": s["dia"],
        "aforo_sint": s["aforo"],
        # aforo en vivo: NaN si no hay (el modelo lo maneja)
        "aforo_vivo": float("nan") if aforo_vivo is None else float(aforo_vivo),
    }
    cut = registro.get("cut")
    curves = registro.get("curves", {})
    for idx in indices:
        pares = curve_pairs(cut, curves.get(idx, []), max_age=max_age)
        f.update(curve_features(idx.lower(), pares))
    return f
