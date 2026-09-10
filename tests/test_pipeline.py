import json
from tchmotor.pipeline import JobEstimados


class FakeSB:
    def __init__(self):
        self.guardadas = []

    def cargar_var_map(self):
        return {"V82": "CC 01-1940", "V102": "CC 05-430"}

    def cargar_aforo_sintetico(self):
        return [
            {"variedad": "CC 05-430", "soca": -1, "poblacion": 11.5, "peso": 1.5, "diametro": 2.8, "aforo_sint": 125},
            {"variedad": "CC 01-1940", "soca": -1, "poblacion": 10.5, "peso": 1.4, "diametro": 2.7, "aforo_sint": 110},
        ]

    def guardar_estimados(self, filas):
        self.guardadas.extend(filas)
        return len(filas)


def _curva(base):
    # 4 puntos mensuales desde el corte
    return {
        idx: [
            {"from": "2025-10-01", "mean": base},
            {"from": "2026-01-01", "mean": base + 0.2},
            {"from": "2026-05-01", "mean": base + 0.35},
            {"from": "2026-08-01", "mean": base + 0.2},
        ]
        for idx in ("NDVI", "NDMI", "EVI")
    }


def extractor_ok(tab_id, planta, cut, harvest):
    # varía la curva con el tab_id para que el modelo tenga algo de señal
    base = 0.45 + (hash(tab_id) % 5) * 0.05
    return _curva(base)


def _dataset(tmp_path):
    p = tmp_path / "ds.jsonl"
    lines = []
    for i in range(12):
        var = "V82" if i % 2 else "V102"
        lines.append(json.dumps({
            "variedad": var, "corte": (i % 6) + 1, "edad": 12.0, "mes": 9, "ha": 5.0,
            "zona_agro": "6H1", "cut": "2025-09-01", "tch": 100 + i * 3,
            "curves": _curva(0.5 + (i % 5) * 0.04),
        }))
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _suertes():
    return [
        {"sec_ste": "3106-160", "planta": "riopaila", "tab_id": "3106-160-T1",
         "cut": "2025-09-01", "harvest": "2026-09-09", "edad": 12.1, "corte": 8,
         "variedad": "CC 01-1940", "zona_agro": "5H3", "ha": 6.4, "area": 6.4,
         "fecha_corte_prevista": "2026-09-09"},
        {"sec_ste": "3102-110", "planta": "riopaila", "tab_id": "3102-110-T2",
         "cut": "2025-09-01", "harvest": "2026-09-09", "edad": 12.2, "corte": 4,
         "variedad": "CC 05-430", "zona_agro": "1H1", "ha": 23.5, "area": 23.5,
         "fecha_corte_prevista": "2026-09-09"},
    ]


def test_entrenar_y_estimar(tmp_path):
    sb = FakeSB()
    job = JobEstimados(sb, extractor_ok, dataset_path=_dataset(tmp_path)).entrenar()
    filas = job.estimar(_suertes(), "2026-09-09", factores={"riopaila": 0.981})
    assert len(filas) == 2
    f = filas[0]
    assert f["sec_ste"] == "3106-160" and f["modo"] == "motor"
    assert f["factor_recal"] == 0.981 and f["modelo_version"]
    assert 40 < f["tch_estimado"] < 240  # estimado plausible
    assert f["ton_estimadas"] == round(f["tch_estimado"] * 6.4, 0)


def test_recalibracion_escala_el_estimado(tmp_path):
    job = JobEstimados(FakeSB(), extractor_ok, dataset_path=_dataset(tmp_path)).entrenar()
    a = job.estimar(_suertes(), "2026-09-09", factores={"riopaila": 1.0})
    b = job.estimar(_suertes(), "2026-09-09", factores={"riopaila": 0.9})
    assert b[0]["tch_estimado"] == round(a[0]["tch_estimado"] * 0.9, 1)


def test_suerte_sin_curva_se_salta(tmp_path):
    def extractor_falla(tab_id, planta, cut, harvest):
        return None if tab_id.startswith("3102") else extractor_ok(tab_id, planta, cut, harvest)

    job = JobEstimados(FakeSB(), extractor_falla, dataset_path=_dataset(tmp_path)).entrenar()
    filas = job.estimar(_suertes(), "2026-09-09")
    assert len(filas) == 1 and filas[0]["sec_ste"] == "3106-160"


def test_correr_escribe_en_supabase(tmp_path):
    sb = FakeSB()
    job = JobEstimados(sb, extractor_ok, dataset_path=_dataset(tmp_path))
    filas, n = job.correr(_suertes(), "2026-09-09", factores={"riopaila": 0.981})
    assert n == 2 and len(sb.guardadas) == 2


def test_fusion_cuando_hay_aforo_vivo(tmp_path):
    from tchmotor.fusion import Fusion
    sb = FakeSB()
    job = JobEstimados(sb, extractor_ok, dataset_path=_dataset(tmp_path),
                       fusion=Fusion(coef_motor=0.5, coef_aforo=0.5, intercepto=0)).entrenar()
    # aforo solo para la primera suerte
    filas = job.estimar(_suertes(), "2026-09-09", factores={"riopaila": 1.0},
                        aforos={"3106-160": 150.0})
    por_sec = {f["sec_ste"]: f for f in filas}
    assert por_sec["3106-160"]["modo"] == "fusion"
    assert por_sec["3102-110"]["modo"] == "motor"
    # con coef 0.5/0.5 e intercepto 0, el fusionado = (motor + 150)/2 > motor solo
    # (el aforo 150 es alto), así que sube respecto al motor puro
