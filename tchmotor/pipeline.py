"""Job de estimados: orquesta extracción → features → modelo → recalibración →
persistencia. Entrena con el dataset histórico y estima las suertes activas.

Dependencias inyectables (Supabase, extractor de curvas) para poder testear sin
red. En producción es un job mensual (P2); la fusión con aforo en vivo (P3) y la
auto-recalibración desde cosechas cerradas (P5) se agregan encima.
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

from .aforo import AforoSinteticoTabla
from .features import build_features
from .fusion import Fusion
from .modelo import MotorTCH

_DATA = Path(__file__).resolve().parent.parent / "data"
VERSION = "v0.1"


class JobEstimados:
    def __init__(self, supabase, extractor, dataset_path: str | Path | None = None,
                 fusion: Fusion | None = None):
        self.sb = supabase
        self.extractor = extractor  # (tab_id, planta, cut, harvest) -> curves | None
        self.var_map = supabase.cargar_var_map()
        self.synth = AforoSinteticoTabla(supabase.cargar_aforo_sintetico())
        self.dataset_path = Path(dataset_path or _DATA / "dataset_entrenamiento.jsonl")
        self.fusion = fusion or Fusion()
        self.motor: MotorTCH | None = None

    def entrenar(self) -> "JobEstimados":
        rows, y = [], []
        for line in open(self.dataset_path, encoding="utf-8"):
            r = json.loads(line)
            if not r.get("curves", {}).get("NDVI"):
                continue
            f = build_features(r, self.synth, self.var_map)  # variedad V## → CC dentro
            if f["ndvi_n"] < 3:
                continue
            rows.append(f)
            y.append(r["tch"])
        X = pd.DataFrame(rows)
        self.motor = MotorTCH().entrenar(X, y)
        return self

    def estimar(self, suertes: list[dict], fecha_corrida: str,
                factores: dict[str, float] | None = None,
                aforos: dict[str, float] | None = None) -> list[dict]:
        """Filas listas para `tch_estimado` (no escribe). Salta suertes sin curva.

        `aforos` = {sec_ste: tch_pesos} del aforo en vivo; donde exista se fusiona
        (modo 'fusion'), si no el estimado es del motor (modo 'motor').
        """
        if self.motor is None:
            raise RuntimeError("entrena el motor antes de estimar")
        factores = factores or {}
        aforos = aforos or {}
        feats, meta = [], []
        for s in suertes:
            aforo = aforos.get(s["sec_ste"])
            curves = self.extractor(s["tab_id"], s["planta"], s["cut"], s["harvest"])
            if curves is None:
                continue
            f = build_features({**s, "curves": curves}, self.synth, self.var_map,
                               aforo_vivo=aforo)
            if f["ndvi_n"] < 3:
                continue
            feats.append(f)
            meta.append((s, aforo))
        if not feats:
            return []
        media, std = self.motor.predecir_con_banda(pd.DataFrame(feats))
        filas = []
        for (s, aforo), m, sd in zip(meta, media, std):
            k = factores.get(s["planta"], 1.0)
            motor_recal = float(m) * k
            if aforo is not None:
                tch = round(self.fusion.combinar(motor_recal, float(aforo)), 1)
                modo = "fusion"
            else:
                tch = round(motor_recal, 1)
                modo = "motor"
            area = s.get("area") or s.get("ha")
            filas.append({
                "sec_ste": s["sec_ste"],
                "planta": s["planta"],
                "fecha_corrida": fecha_corrida,
                "fecha_corte_prevista": s.get("fecha_corte_prevista"),
                "edad_meses": s.get("edad"),
                "soca": s.get("corte"),
                "variedad": s.get("variedad"),
                "tch_estimado": tch,
                "tch_std": round(float(sd), 1),
                "ton_estimadas": round(tch * area, 0) if area else None,
                "area_ha": area,
                "modo": modo,
                "factor_recal": k,
                "modelo_version": VERSION,
            })
        return filas

    def correr(self, suertes: list[dict], fecha_corrida: str,
               factores: dict[str, float] | None = None,
               aforos: dict[str, float] | None = None):
        """Entrena (si hace falta), estima y escribe en tch_estimado."""
        if self.motor is None:
            self.entrenar()
        filas = self.estimar(suertes, fecha_corrida, factores, aforos)
        n = self.sb.guardar_estimados(filas)
        return filas, n
