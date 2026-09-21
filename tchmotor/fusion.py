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

# Coeficientes re-ajustados con las 28 cosechas de septiembre-2026 (Cosecha de
# campo, mismo ciclo cortado, soca-limpio), aforo=promedio de los métodos. Bajan el
# sesgo de la fusión de +5,5 % a 0,0 % y el MAPE de 10,0 % a 8,6 %: el aforo físico
# también sobreestimó las suertes bajas, por eso el peso del aforo cae de 0,35 a
# 0,14 y el intercepto sube. Se ajustaron en la ESCALA del motor recalibrado con el
# factor vigente (tch_factor riopaila k=0,9557), que es lo que la corrida le pasa a
# `combinar`; si ese factor del motor cambia, hay que RE-AJUSTAR la fusión.
# Re-ajustar cada campaña (y a medida que cierran más meses: sept es un mes bajo)
# con `scripts/reajustar_fusion.py` (usa `ajustar`).
# Anteriores (77 cosechas, MAPE 9,1 %): 0.5208 / 0.3456 / 10.2058.
COEF_MOTOR = 0.5183
COEF_AFORO = 0.1402
INTERCEPTO = 30.0364


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
