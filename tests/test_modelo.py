import numpy as np
import pandas as pd
from tchmotor.modelo import MotorTCH


def _datos(n=40, seed=0):
    rng = np.random.default_rng(seed)
    var = rng.choice(["CC 05-430", "CC 01-1940", "CC 09-066"], n)
    df = pd.DataFrame(
        {
            "corte": rng.integers(1, 10, n).astype(float),
            "edad": rng.uniform(11, 13, n),
            "ndvi_peak": rng.uniform(0.6, 0.85, n),
            "ndmi_gg": rng.uniform(0.1, 0.4, n),
            "aforo_sint": rng.uniform(90, 140, n),
            "variedad": var,
        }
    )
    # TCH sintético con algo de señal en ndvi/aforo
    y = 40 + 60 * df.ndvi_peak + 0.3 * df.aforo_sint + rng.normal(0, 5, n)
    return df, y.values


def test_entrenar_y_predecir():
    df, y = _datos()
    m = MotorTCH(n_estimators=50).entrenar(df, y)
    p = m.predecir(df)
    assert p.shape == (len(y),)
    assert np.isfinite(p).all()


def test_variedad_nueva_no_rompe_prediccion():
    df, y = _datos()
    m = MotorTCH(n_estimators=50).entrenar(df, y)
    nuevo = df.head(3).copy()
    nuevo["variedad"] = "CC 99-9999"  # variedad no vista → cae a 'otras'
    p = m.predecir(nuevo)
    assert p.shape == (3,) and np.isfinite(p).all()


def test_banda_de_incertidumbre():
    df, y = _datos()
    m = MotorTCH(n_estimators=50).entrenar(df, y)
    media, desv = m.predecir_con_banda(df)
    assert media.shape == desv.shape == (len(y),)
    assert (desv >= 0).all()


def test_predecir_sin_entrenar_lanza():
    import pytest

    with pytest.raises(RuntimeError):
        MotorTCH().predecir(_datos()[0])
