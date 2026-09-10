import pytest
from tchmotor.recalibracion import factor, aplicar, diagnosticos, por_planta


def test_factor_ponderado_por_area():
    # estimado 100, real 95, misma área → factor 0.95
    assert factor([100, 100], [95, 95], [1, 1]) == pytest.approx(0.95)


def test_factor_pondera_por_toneladas_no_promedio_de_tch():
    # suerte grande (10 ha) pesa más que la chica (1 ha)
    k = factor([100, 100], [90, 130], [10, 1])
    # Σreal·área = 900+130=1030 ; Σest·área = 1000+100=1100 → 0.936
    assert k == pytest.approx(1030 / 1100)


def test_aplicar():
    assert aplicar(120.0, 0.95) == pytest.approx(114.0)


def test_factor_rechaza_datos_invalidos():
    with pytest.raises(ValueError):
        factor([], [], [])
    with pytest.raises(ValueError):
        factor([0], [90], [1])  # estimado agregado 0


def test_diagnosticos_coincide_con_factor_y_reporta_sesgo():
    d = diagnosticos([100, 100], [90, 130], [10, 1])
    assert d["factor"] == pytest.approx(1030 / 1100)      # mismo que factor()
    assert d["n"] == 2 and d["area_ha"] == 11
    # el estimado corre caliente: est_agg 1100 > real_agg 1030 → sesgo positivo
    assert d["sesgo_pct"] == pytest.approx((1100 / 1030 - 1) * 100, abs=0.01)
    assert d["mape"] > 0


def test_diagnosticos_estimado_perfecto_factor_uno():
    d = diagnosticos([100, 120], [100, 120], [3, 5])
    assert d["factor"] == pytest.approx(1.0)
    assert d["sesgo_pct"] == pytest.approx(0.0)
    assert d["mape"] == pytest.approx(0.0)


def test_por_planta_separa_y_diagnostica():
    regs = [
        {"planta": "riopaila", "estimado": 100, "real": 98, "area": 10},
        {"planta": "riopaila", "estimado": 100, "real": 98, "area": 5},
        {"planta": "castilla", "estimado": 100, "real": 90, "area": 8},
    ]
    out = por_planta(regs)
    assert set(out) == {"riopaila", "castilla"}
    assert out["riopaila"]["factor"] == pytest.approx(0.98)
    assert out["castilla"]["factor"] == pytest.approx(0.90)
    assert out["riopaila"]["n"] == 2 and out["castilla"]["n"] == 1
