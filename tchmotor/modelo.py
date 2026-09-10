"""Modelo de estimación de TCH (Random Forest) sobre el vector de features.

Encapsula el one-hot de variedad (top-K con "otras"), el entrenamiento y la
predicción, alineando las columnas entre entrenar y predecir para que una
variedad nueva no rompa la inferencia.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor


class MotorTCH:
    def __init__(self, n_estimators: int = 600, min_samples_leaf: int = 3,
                 max_features: float = 0.5, top_variedades: int = 12, random_state: int = 0):
        self.p = dict(n_estimators=n_estimators, min_samples_leaf=min_samples_leaf,
                      max_features=max_features, n_jobs=-1, random_state=random_state)
        self.top_k = top_variedades
        self.top_: list[str] = []
        self.cols_: list[str] = []
        self.rf_: RandomForestRegressor | None = None

    def _matriz(self, df: pd.DataFrame, entrenando: bool) -> pd.DataFrame:
        d = df.copy()
        if entrenando:
            self.top_ = list(d["variedad"].value_counts().head(self.top_k).index)
        var = d["variedad"].where(d["variedad"].isin(self.top_), "otras")
        cat = pd.get_dummies(var, prefix="v")
        base = d.drop(columns=["variedad"])
        X = pd.concat([base, cat], axis=1).astype(float)
        if entrenando:
            self.cols_ = list(X.columns)
            return X
        return X.reindex(columns=self.cols_, fill_value=0)

    def entrenar(self, features: pd.DataFrame, tch: np.ndarray) -> "MotorTCH":
        X = self._matriz(features, entrenando=True)
        self.rf_ = RandomForestRegressor(**self.p).fit(X, tch)
        return self

    def predecir(self, features: pd.DataFrame) -> np.ndarray:
        if self.rf_ is None:
            raise RuntimeError("el motor no está entrenado")
        return self.rf_.predict(self._matriz(features, entrenando=False))

    def predecir_con_banda(self, features: pd.DataFrame):
        """Predicción media + desviación entre árboles (incertidumbre)."""
        if self.rf_ is None:
            raise RuntimeError("el motor no está entrenado")
        X = self._matriz(features, entrenando=False)
        arb = np.stack([t.predict(X.values) for t in self.rf_.estimators_])
        return arb.mean(0), arb.std(0)
