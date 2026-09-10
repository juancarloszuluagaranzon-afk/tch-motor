import json
import pytest
from tchmotor.persistencia import Supabase


class FakeHTTP:
    """Registra las llamadas y devuelve respuestas encoladas."""

    def __init__(self):
        self.calls = []
        self.respuestas = []

    def __call__(self, method, url, headers, body):
        self.calls.append(dict(method=method, url=url, headers=headers,
                               body=json.loads(body) if body else None))
        return self.respuestas.pop(0)


def cliente(http):
    return Supabase(url="https://x.supabase.co", key="svc-key", http=http)


def test_exige_credenciales():
    with pytest.raises(ValueError):
        Supabase(url="", key="", http=lambda *a: (200, "[]"))


def test_headers_llevan_apikey_y_bearer():
    h = FakeHTTP()
    h.respuestas.append((200, "[]"))
    cliente(h).leer("tch_estimado")
    hdr = h.calls[0]["headers"]
    assert hdr["apikey"] == "svc-key"
    assert hdr["Authorization"] == "Bearer svc-key"


def test_cargar_var_map_arma_diccionario():
    h = FakeHTTP()
    h.respuestas.append((200, json.dumps([
        {"codigo": "V82", "nombre": "CC 01-1940"},
        {"codigo": "V39", "nombre": "CC 85-92"},
    ])))
    vm = cliente(h).cargar_var_map()
    assert vm == {"V82": "CC 01-1940", "V39": "CC 85-92"}
    assert "tch_var_map" in h.calls[0]["url"]


def test_guardar_estimados_upsert_por_suerte_y_fecha():
    h = FakeHTTP()
    h.respuestas.append((201, ""))
    filas = [{"sec_ste": "3106-160", "planta": "riopaila",
              "fecha_corrida": "2026-09-09", "tch_estimado": 104.0}]
    n = cliente(h).guardar_estimados(filas)
    assert n == 1
    c = h.calls[0]
    assert c["method"] == "POST"
    assert "on_conflict=sec_ste,fecha_corrida" in c["url"]
    assert "merge-duplicates" in c["headers"]["Prefer"]
    assert c["body"] == filas


def test_upsert_vacio_no_llama_red():
    h = FakeHTTP()
    assert cliente(h).guardar_estimados([]) == 0
    assert h.calls == []


def test_error_http_lanza():
    h = FakeHTTP()
    h.respuestas.append((401, "no autorizado"))
    with pytest.raises(RuntimeError):
        cliente(h).leer("tch_estimado")
