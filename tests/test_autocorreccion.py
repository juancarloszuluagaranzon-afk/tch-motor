import pytest
from tchmotor.autocorreccion import JobRecalibracion


class FakeSB:
    def __init__(self, estimados, reales):
        self._est = estimados
        self._real = reales
        self.guardadas = []

    def cargar_estimados(self, fecha_corrida=None):
        if fecha_corrida is None:
            return self._est
        return [e for e in self._est if e["fecha_corrida"] == fecha_corrida]

    def cargar_reales(self, campana=None):
        return self._real

    def guardar_factores(self, filas):
        self.guardadas.extend(filas)
        return len(filas)


def _estimados():
    return [
        # riopaila: crudo 100 (98/0.98), dos suertes
        {"sec_ste": "3106-160", "planta": "riopaila", "fecha_corrida": "2026-06-01",
         "modo": "motor", "factor_recal": 0.98, "tch_estimado": 98.0, "area_ha": 10.0},
        {"sec_ste": "3106-140", "planta": "riopaila", "fecha_corrida": "2026-06-01",
         "modo": "motor", "factor_recal": 0.98, "tch_estimado": 98.0, "area_ha": 5.0},
        # fusion → se ignora aunque tenga real
        {"sec_ste": "3106-999", "planta": "riopaila", "fecha_corrida": "2026-06-01",
         "modo": "fusion", "factor_recal": 0.98, "tch_estimado": 120.0, "area_ha": 3.0},
        # castilla: crudo 100 (90/0.90)
        {"sec_ste": "5000-100", "planta": "castilla", "fecha_corrida": "2026-06-01",
         "modo": "motor", "factor_recal": 0.90, "tch_estimado": 90.0, "area_ha": 8.0},
        # motor sin real → se ignora
        {"sec_ste": "3106-777", "planta": "riopaila", "fecha_corrida": "2026-06-01",
         "modo": "motor", "factor_recal": 0.98, "tch_estimado": 98.0, "area_ha": 4.0},
    ]


def _reales():
    return [
        {"sec_ste": "3106-160", "planta": "riopaila", "tch_real": 98.0, "area_ha": 10.0},
        {"sec_ste": "3106-140", "planta": "riopaila", "tch_real": 98.0, "area_ha": 5.0},
        {"sec_ste": "3106-999", "planta": "riopaila", "tch_real": 118.0, "area_ha": 3.0},
        {"sec_ste": "5000-100", "planta": "castilla", "tch_real": 90.0, "area_ha": 8.0},
    ]


def test_empareja_solo_motor_con_real():
    job = JobRecalibracion(FakeSB(_estimados(), _reales()))
    regs = job.emparejar("2026")
    secs = sorted(r["planta"] for r in regs)
    # 2 riopaila + 1 castilla = 3 (fusion y motor-sin-real fuera)
    assert len(regs) == 3
    # el crudo se recupera dividiendo por el factor viejo
    rio = [r for r in regs if r["planta"] == "riopaila"][0]
    assert rio["crudo"] == pytest.approx(100.0)


def test_factor_por_planta():
    job = JobRecalibracion(FakeSB(_estimados(), _reales()))
    filas = job.calcular("2026", vigente_desde="2026-06-01")
    por = {f["planta"]: f for f in filas}
    assert set(por) == {"riopaila", "castilla"}
    # riopaila: real (98·10+98·5)/crudo(100·10+100·5) = 1470/1500 = 0.98
    assert por["riopaila"]["factor"] == pytest.approx(0.98, abs=1e-4)
    assert por["riopaila"]["n_suertes"] == 2
    # castilla: 90/100 = 0.90
    assert por["castilla"]["factor"] == pytest.approx(0.90, abs=1e-4)
    # el crudo de castilla corre caliente +11.1% (100 vs 90)
    assert por["castilla"]["sesgo_pct"] == pytest.approx((100 / 90 - 1) * 100, abs=0.01)
    assert por["riopaila"]["vigente_desde"] == "2026-06-01"


def test_correr_escribe_factores():
    sb = FakeSB(_estimados(), _reales())
    filas, n = JobRecalibracion(sb).correr("2026", vigente_desde="2026-06-01")
    assert n == 2 and len(sb.guardadas) == 2


def test_sin_cortes_cerrados_no_produce_filas():
    job = JobRecalibracion(FakeSB(_estimados(), []))
    assert job.calcular("2026") == []
