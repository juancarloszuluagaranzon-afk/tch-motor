"""Recalibración por planta/campaña.

El modelo, entrenado con años de mayor rendimiento, corre "caliente"
(sobreestima) frente a una campaña más baja. El factor multiplicativo se deriva
de las cosechas YA CERRADAS del año (real/estimado, ponderado por área) y se
aplica a las suertes aún en pie. Debe re-derivarse cada campaña y por planta
(Riopaila corría +1.9%, Castilla +6.4% → factores distintos).
"""
from __future__ import annotations
from typing import Sequence


def factor(estimado: Sequence[float], real: Sequence[float], area: Sequence[float]) -> float:
    """Factor ponderado por área = Σ(real·área) / Σ(estimado·área).

    Usa el agregado en toneladas (no el promedio de TCH) porque es el número
    financiero. Lanza si no hay datos o el estimado agregado es 0.
    """
    if not (len(estimado) == len(real) == len(area)) or not estimado:
        raise ValueError("estimado, real y area deben tener el mismo largo (>0)")
    num = sum(r * a for r, a in zip(real, area))
    den = sum(e * a for e, a in zip(estimado, area))
    if den <= 0:
        raise ValueError("estimado agregado <= 0")
    return num / den


def aplicar(estimado: float, k: float) -> float:
    """Aplica el factor de recalibración a un estimado crudo."""
    return estimado * k


def diagnosticos(estimado: Sequence[float], real: Sequence[float],
                 area: Sequence[float]) -> dict:
    """Diagnóstico agregado de un conjunto estimado vs real (ponderado por área).

    `factor` = corrección multiplicativa que haría casar el agregado (real/est).
    Con el estimado CRUDO da el factor a aplicar; con el estimado REPORTADO da el
    residual (idealmente ~1). `sesgo_pct` > 0 = el estimado corre caliente.
    """
    if not (len(estimado) == len(real) == len(area)) or not estimado:
        raise ValueError("estimado, real y area deben tener el mismo largo (>0)")
    real_agg = sum(r * a for r, a in zip(real, area))
    est_agg = sum(e * a for e, a in zip(estimado, area))
    if est_agg <= 0 or real_agg <= 0:
        raise ValueError("agregado <= 0")
    ape = [abs(e - r) / r for e, r in zip(estimado, real) if r > 0]
    return {
        "n": len(estimado),
        "area_ha": round(sum(area), 2),
        "tch_real_agg": round(real_agg, 1),
        "tch_est_agg": round(est_agg, 1),
        "factor": real_agg / est_agg,
        "sesgo_pct": round((est_agg / real_agg - 1) * 100, 2),
        "mape": round(100 * sum(ape) / len(ape), 2) if ape else None,
    }


def por_planta(registros: Sequence[dict]) -> dict[str, dict]:
    """Agrupa registros {planta, estimado, real, area} y saca el diagnóstico de
    cada planta. Cada registro debe traer el estimado CRUDO (para el factor)."""
    grupos: dict[str, list] = {}
    for r in registros:
        grupos.setdefault(r["planta"], []).append(r)
    salida = {}
    for planta, rs in grupos.items():
        salida[planta] = diagnosticos(
            [x["estimado"] for x in rs],
            [x["real"] for x in rs],
            [x["area"] for x in rs],
        )
    return salida
