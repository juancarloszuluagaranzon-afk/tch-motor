import math
from tchmotor.aforo import (
    peso_por_diametro,
    tch_por_pesos,
    tch_por_diametro,
    AforoSintetico,
)


def test_peso_por_diametro_geometria():
    # cilindro de 2.86 cm de diámetro y 228 cm de largo, densidad de la caña
    esperado = (math.pi / 4) * 2.86 * 2.86 * 228 * 0.00104
    assert peso_por_diametro(2.86, 228) == esperado
    assert abs(esperado - 1.523) < 0.02  # ~1.5 kg/tallo, valor de campo plausible


def test_tch_por_pesos_formula_de_campo():
    # 10 tallos/m, 1.5 kg/tallo, surcos a 1.65 m → 10·1.5·(10/1.65) ≈ 90.9
    assert abs(tch_por_pesos(10, 1.5, 1.65) - 90.9) < 0.2


def test_espaciamiento_cero_no_divide_por_cero():
    assert tch_por_pesos(10, 1.5, 0) == 0.0


def test_tch_por_diametro_usa_peso_calculado():
    esperado = tch_por_pesos(10, peso_por_diametro(2.86, 228), 1.65)
    assert tch_por_diametro(10, 2.86, 228, 1.65) == esperado


def _regs():
    return [
        {"variedad": "CC 05-430", "soca": 2, "pob": 11.0, "peso": 1.5, "dia": 2.8, "tch": 120},
        {"variedad": "CC 05-430", "soca": 2, "pob": 13.0, "peso": 1.5, "dia": 2.8, "tch": 130},
        {"variedad": "CC 05-430", "soca": 2, "pob": 12.0, "peso": 1.5, "dia": 2.8, "tch": 125},
        {"variedad": "CC 05-430", "soca": 2, "pob": 12.0, "peso": 1.5, "dia": 2.8, "tch": 124},
        {"variedad": "CC 05-430", "soca": 8, "pob": 9.0, "peso": 1.4, "dia": 2.6, "tch": 100},
    ]


def test_sintetico_var_soca_toma_la_mediana():
    a = AforoSintetico(_regs(), min_n=4)
    r = a.lookup("CC 05-430", 2)  # 4 registros → tiene tabla var×soca
    assert r["pob"] == 12.0 and r["aforo"] == 124.5


def test_sintetico_tolera_soca_nan():
    # registros sin soca (NaN) no deben romper la construcción
    regs = _regs() + [{"variedad": "CC 05-430", "soca": float("nan"),
                       "pob": 10.0, "peso": 1.4, "dia": 2.6, "tch": 105}]
    a = AforoSintetico(regs, min_n=4)
    assert a.lookup("CC 05-430", float("nan"))["pob"] is not None  # cae a variedad
    assert a.lookup("CC 05-430", 2)["aforo"] == 124.5


def test_sintetico_filas_para_bd():
    a = AforoSintetico(_regs(), min_n=4)
    filas = a.filas()
    # una fila var×soca (CC 05-430, soca 2) + una var-level (soca -1)
    vs = [f for f in filas if f["soca"] == 2]
    vlvl = [f for f in filas if f["soca"] == -1]
    assert len(vs) == 1 and vs[0]["aforo_sint"] == 124.5 and vs[0]["n"] == 4
    assert len(vlvl) == 1 and vlvl[0]["variedad"] == "CC 05-430"


def test_sintetico_respaldo_a_variedad_y_global():
    a = AforoSintetico(_regs(), min_n=4)
    # soca 8 tiene 1 registro (< min_n) → respaldo a la variedad (5 registros)
    r = a.lookup("CC 05-430", 8)
    assert r["pob"] == 12.0  # mediana de la variedad completa
    # variedad desconocida → respaldo global
    g = a.lookup("XX 00-000", 3)
    assert g["pob"] == 12.0


def test_sintetico_tabla_desde_bd():
    from tchmotor.aforo import AforoSinteticoTabla
    filas = [
        {"variedad": "CC 05-430", "soca": 2, "poblacion": 12.0, "peso": 1.5, "diametro": 2.8, "aforo_sint": 124.5},
        {"variedad": "CC 05-430", "soca": -1, "poblacion": 11.5, "peso": 1.5, "diametro": 2.8, "aforo_sint": 120.0},
    ]
    t = AforoSinteticoTabla(filas)
    assert t.lookup("CC 05-430", 2)["aforo"] == 124.5      # var×soca
    assert t.lookup("CC 05-430", 9)["aforo"] == 120.0      # respaldo variedad (soca -1)
    assert t.lookup("XX 00-000", 3)["aforo"] == 120.0      # global
