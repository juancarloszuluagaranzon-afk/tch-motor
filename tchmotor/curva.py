"""Features de la curva temporal satelital de un índice (NDVI/NDMI/EVI…).

La serie viene de `/api/sentinel-stats?interval=P30D` como una lista de puntos
`{from, mean}`. Aquí se convierte a pares (edad_en_meses, valor) y se resumen
en features robustas a huecos por nube: pico, media, integral (AUC, proxy de
biomasa), vigor de gran-crecimiento (meses 4-9), pendientes, etc.

`max_age` permite truncar la curva a la edad de HOY para proyectar caña joven
(modelo edad-consciente): solo entran los puntos hasta esa edad.
"""
from __future__ import annotations
from datetime import date
import numpy as np

_DIAS_MES = 30.44


def curve_pairs(cut_iso: str, serie, max_age: float | None = None):
    """Lista ordenada de (edad_meses, valor) de una serie, saltando nubes/huecos."""
    cut = date.fromisoformat(cut_iso)
    pts = []
    for p in serie or []:
        m = p.get("mean")
        f = p.get("from")
        if m is None or not f:
            continue
        edad = (date.fromisoformat(f[:10]) - cut).days / _DIAS_MES + 0.5
        if edad <= 0 or edad >= 16:
            continue
        if max_age is not None and edad > max_age:
            continue
        pts.append((edad, float(m)))
    pts.sort()
    return pts


def limpiar_nube(pares, umbral: float = 0.30):
    """Corrige picos/valles AISLADOS de nube en una serie [(edad, valor)] ordenada por edad.

    Un punto es nube solo si queda fuera del rango de sus dos vecinos y se desvía más de `umbral`
    (fracción) de la interpolación entre ellos; se reemplaza por esa interpolación. Los tramos
    sostenidos (estrés, riego, maduración) no son extremos aislados y quedan intactos.
    """
    out = list(pares)
    for i in range(1, len(pares) - 1):
        (e0, v0), (e1, v1), (e2, v2) = pares[i - 1], pares[i], pares[i + 1]
        if e2 == e0:
            continue
        lin = v0 + (v2 - v0) * (e1 - e0) / (e2 - e0)
        if lin > 0 and (v1 < min(v0, v2) or v1 > max(v0, v2)) and abs(v1 - lin) / lin > umbral:
            out[i] = (e1, lin)
    return out


def curve_features(nombre: str, pares) -> dict:
    """Resume la curva en features. Con < 3 puntos válidos devuelve NaN (nubes)."""
    ks = ["mean", "peak", "min", "gg", "early", "last", "slope", "rng", "n"]
    if len(pares) < 3:
        f = {f"{nombre}_{k}": float("nan") for k in ks}
        f[f"{nombre}_n"] = len(pares)
        return f
    xs = np.array([a for a, _ in pares])
    ys = np.array([v for _, v in pares])
    gg = [v for a, v in pares if 4 <= a <= 9]
    return {
        f"{nombre}_mean": float(ys.mean()),
        f"{nombre}_peak": float(ys.max()),
        f"{nombre}_min": float(ys.min()),
        f"{nombre}_rng": float(ys.max() - ys.min()),
        f"{nombre}_gg": float(np.mean(gg)) if gg else float(ys.mean()),
        f"{nombre}_early": float(np.interp(min(2, xs.max()), xs, ys)),
        f"{nombre}_last": float(ys[-1]),
        f"{nombre}_slope": float(ys[-1] - ys[0]),
        f"{nombre}_n": len(pares),
    }
