import math
from tchmotor.curva import curve_pairs, curve_features


def _serie():
    # cut = 2025-01-01; puntos ~mensuales, uno con nube (mean=None)
    return [
        {"from": "2025-02-01", "mean": 0.30},
        {"from": "2025-04-01", "mean": 0.55},
        {"from": "2025-06-01", "mean": 0.75},  # pico
        {"from": "2025-07-01", "mean": None},  # nube → se salta
        {"from": "2025-09-01", "mean": 0.60},
    ]


def test_curve_pairs_edad_y_salta_nubes():
    p = curve_pairs("2025-01-01", _serie())
    assert len(p) == 4  # el punto con mean=None no entra
    # 2025-02-01 → ~1 mes de edad (31 días / 30.44 + 0.5)
    assert abs(p[0][0] - (31 / 30.44 + 0.5)) < 1e-6
    assert p[0][1] == 0.30


def test_curve_pairs_trunca_por_max_age():
    # a 3 meses de edad solo entran los primeros puntos
    p = curve_pairs("2025-01-01", _serie(), max_age=3)
    assert all(edad <= 3 for edad, _ in p)
    assert len(p) < 4


def test_curve_features_resumen():
    p = curve_pairs("2025-01-01", _serie())
    f = curve_features("ndvi", p)
    assert f["ndvi_peak"] == 0.75
    assert f["ndvi_n"] == 4
    assert f["ndvi_min"] == 0.30
    assert abs(f["ndvi_rng"] - 0.45) < 1e-9


def test_curve_features_pocos_puntos_es_nan():
    f = curve_features("ndvi", [(1.0, 0.3), (2.0, 0.5)])  # < 3
    assert math.isnan(f["ndvi_peak"])
    assert f["ndvi_n"] == 2
