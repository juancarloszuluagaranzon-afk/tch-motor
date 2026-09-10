"""Fusión motor + aforo en vivo.

El motor (satélite) y el aforo físico ven cosas distintas y se equivocan
distinto (errores independientes), así que combinarlos gana: validado a nivel
Nax (MAPE 10 %, ±20 % 86-87 %). La fusión es un combinador lineal
`tch = a·motor + b·aforo + c` cuyos coeficientes se derivaron de la validación
2026 (225 suertes) y **deben re-ajustarse cada campaña** (como la recalibración).
El intercepto absorbe el sesgo optimista del aforo.

Se aplica SOLO cuando hay aforo en vivo; sin aforo, el estimado es el del motor.
"""
from __future__ import annotations

# Coeficientes por defecto (validación 2026, n=225). Re-ajustables con `ajustar`.
COEF_MOTOR = 0.4333
COEF_AFORO = 0.3147
INTERCEPTO = 21.8363


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
