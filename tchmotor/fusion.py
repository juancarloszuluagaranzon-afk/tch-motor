"""Fusión motor + aforo en vivo.

El motor (satélite) y el aforo físico ven cosas distintas y se equivocan
distinto (errores independientes), así que combinarlos gana: validado sobre 77
cosechas 2026 del mismo ciclo cortado, la fusión baja el MAPE de 12,5 % (solo
motor) / 15,1 % (solo aforo) a **9,1 % (±20 % 92 %)**. La fusión es un combinador
lineal `tch = a·motor + b·aforo + c` cuyos coeficientes se re-derivaron con el
aforo = PROMEDIO de los 3 métodos (diámetro, día-12-meses, pesos), que es el mejor
(MAPE 14,4 % vs 19,4 % de 'pesos' solo). **Deben re-ajustarse cada campaña** con
`ajustar` (como la recalibración). El intercepto absorbe el sesgo del aforo.

IMPORTANTE: el `aforo` que entra a `combinar` debe ser el PROMEDIO de los 3
métodos (lo que devuelve `aforo_vivo.aforos_vigentes`), no solo 'pesos'.

Se aplica SOLO cuando hay aforo en vivo; sin aforo, el estimado es el del motor.
"""
from __future__ import annotations

# Coeficientes por defecto (regresión sobre 77 cosechas 2026, aforo=promedio de los
# 3 métodos; MAPE 9,1 %). Re-ajustables con `ajustar` cada campaña.
COEF_MOTOR = 0.5208
COEF_AFORO = 0.3456
INTERCEPTO = 10.2058


class Fusion:
    def __init__(self, coef_motor=COEF_MOTOR, coef_aforo=COEF_AFORO, intercepto=INTERCEPTO):
        self.coef_motor = coef_motor
        self.coef_aforo = coef_aforo
        self.intercepto = intercepto

    def combinar(self, motor: float, aforo: float) -> float:
        """TCH fusionado a partir del estimado del motor y el aforo físico."""
        return self.coef_motor * motor + self.coef_aforo * aforo + self.intercepto

    @classmethod
    def ajustar(cls, motor, aforo, real) -> "Fusion":
        """Re-deriva los coeficientes de (motor, aforo, real) — una campaña nueva."""
        from sklearn.linear_model import LinearRegression

        X = [[m, a] for m, a in zip(motor, aforo)]
        lr = LinearRegression().fit(X, list(real))
        return cls(float(lr.coef_[0]), float(lr.coef_[1]), float(lr.intercept_))
