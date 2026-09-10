import math
from tchmotor.aforo import AforoSintetico
from tchmotor.features import build_features


VM = {"V82": "CC 01-1940"}
SINT = AforoSintetico(
    [
        {"variedad": "CC 01-1940", "soca": 8, "pob": 10.0, "peso": 1.4, "dia": 2.7, "tch": 110},
        {"variedad": "CC 01-1940", "soca": 8, "pob": 11.0, "peso": 1.4, "dia": 2.7, "tch": 112},
        {"variedad": "CC 01-1940", "soca": 8, "pob": 10.5, "peso": 1.4, "dia": 2.7, "tch": 111},
        {"variedad": "CC 01-1940", "soca": 8, "pob": 10.5, "peso": 1.4, "dia": 2.7, "tch": 113},
    ],
    min_n=4,
)

REG = {
    "variedad": "V82",  # código interno del ZQM
    "corte": 8,
    "edad": 12.0,
    "mes": 9,
    "ha": 5.0,
    "zona_agro": "6H1",
    "cut": "2025-09-01",
    "curves": {
        "NDVI": [
            {"from": "2025-10-01", "mean": 0.3},
            {"from": "2026-01-01", "mean": 0.6},
            {"from": "2026-05-01", "mean": 0.75},
            {"from": "2026-08-01", "mean": 0.6},
        ],
        "NDMI": [],
        "EVI": [],
    },
}


def test_build_features_mapea_variedad_y_zona():
    f = build_features(REG, SINT, VM)
    assert f["variedad"] == "CC 01-1940"  # V82 traducido
    assert f["soilgrp"] == 6 and f["humedad"] == 1


def test_build_features_incluye_aforo_sintetico():
    f = build_features(REG, SINT, VM)
    assert f["aforo_sint"] == 111.5  # mediana del TCH histórico de esa var×soca
    assert f["hist_pob"] == 10.5


def test_build_features_aforo_vivo_opcional():
    sin = build_features(REG, SINT, VM)
    assert math.isnan(sin["aforo_vivo"])
    con = build_features(REG, SINT, VM, aforo_vivo=118.0)
    assert con["aforo_vivo"] == 118.0


def test_build_features_curva_ndvi():
    f = build_features(REG, SINT, VM)
    assert f["ndvi_peak"] == 0.75
    assert f["ndvi_n"] == 4
    assert math.isnan(f["ndmi_peak"])  # NDMI vacío → NaN


def test_build_features_trunca_a_edad_joven():
    # a 3 meses (max_age=3) la curva se recorta
    f = build_features(REG, SINT, VM, max_age=3)
    assert f["ndvi_n"] < 4
