from tchmotor.fusion import Fusion, COEF_MOTOR, COEF_AFORO, INTERCEPTO


def test_combinar_con_coeficientes_por_defecto():
    f = Fusion()
    esperado = COEF_MOTOR * 120 + COEF_AFORO * 130 + INTERCEPTO
    assert f.combinar(120, 130) == esperado


def test_combinar_pondera_ambos():
    f = Fusion(coef_motor=0.5, coef_aforo=0.5, intercepto=0)
    assert f.combinar(100, 140) == 120  # promedio simple


def test_ajustar_recupera_coeficientes():
    # datos generados por 0.6*motor + 0.3*aforo + 10 (motor y aforo NO colineales)
    motor = [100, 120, 90, 110, 130]
    aforo = [105, 140, 95, 100, 150]
    real = [0.6 * m + 0.3 * a + 10 for m, a in zip(motor, aforo)]
    f = Fusion.ajustar(motor, aforo, real)
    assert abs(f.coef_motor - 0.6) < 1e-6
    assert abs(f.coef_aforo - 0.3) < 1e-6
    assert abs(f.intercepto - 10) < 1e-6
