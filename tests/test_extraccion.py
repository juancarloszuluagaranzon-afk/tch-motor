import json
import math
from tchmotor.extraccion import build_url, parse_series, serie_indice, curva_suerte


def test_build_url_lleva_los_parametros():
    u = build_url("http://x/api", "3102-110-T2", "riopaila", "NDVI",
                  "2025-01-01", "2026-01-01")
    assert "index=NDVI" in u and "interval=P30D" in u and "maxcc=60" in u
    assert "tab_id=3102-110-T2" in u and "from=2025-01-01" in u and "to=2026-01-01" in u


def test_parse_series_traduce_null_y_nan_a_none():
    payload = {
        "series": [
            {"from": "2025-01-01", "stats": {"mean": 0.42}},
            {"from": "2025-02-01", "stats": None},          # nube
            {"from": "2025-03-01", "stats": {"mean": "NaN"}},  # todo nube (SCL)
        ]
    }
    s = parse_series(payload)
    assert s[0]["mean"] == 0.42
    assert s[1]["mean"] is None
    assert s[2]["mean"] is None


def test_parse_series_vacia():
    assert parse_series({}) == []
    assert parse_series({"series": None}) == []


class _Resp:
    def __init__(self, obj):
        self._b = json.dumps(obj).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_serie_indice_ok_con_opener_falso():
    payload = {"series": [{"from": "2025-01-01", "stats": {"mean": 0.5}}]}
    abrir = lambda url, timeout: _Resp(payload)
    s = serie_indice("t", "riopaila", "NDVI", "2025-01-01", "2026-01-01",
                     abrir=abrir, dormir=lambda *_: None)
    assert s == [{"from": "2025-01-01", "mean": 0.5}]


def test_serie_indice_reintenta_y_no_cachea_error():
    llamados = {"n": 0}

    def abrir(url, timeout):
        llamados["n"] += 1
        # las 2 primeras dan respuesta de error (sin 'series'), la 3ª es buena
        if llamados["n"] < 3:
            return _Resp({"configured": True, "stats": None, "error": "stats 429"})
        return _Resp({"series": [{"from": "2025-01-01", "stats": {"mean": 0.7}}]})

    s = serie_indice("t", "riopaila", "NDVI", "2025-01-01", "2026-01-01",
                     abrir=abrir, dormir=lambda *_: None, reintentos=6)
    assert s == [{"from": "2025-01-01", "mean": 0.7}]
    assert llamados["n"] == 3


def test_serie_indice_devuelve_none_si_falla_siempre():
    def abrir(url, timeout):
        raise OSError("sin red")

    s = serie_indice("t", "riopaila", "NDVI", "2025-01-01", "2026-01-01",
                     abrir=abrir, dormir=lambda *_: None, reintentos=3)
    assert s is None


def test_curva_suerte_junta_indices():
    payload = {"series": [{"from": "2025-01-01", "stats": {"mean": 0.5}}]}
    abrir = lambda url, timeout: _Resp(payload)
    c = curva_suerte("t", "riopaila", "2025-01-01", "2026-01-01",
                     indices=("NDVI", "NDMI"), abrir=abrir, dormir=lambda *_: None)
    assert set(c) == {"NDVI", "NDMI"}
    assert c["NDVI"][0]["mean"] == 0.5
