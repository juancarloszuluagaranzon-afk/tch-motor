from tchmotor.aforo_vivo import aforos_vigentes


class FakeTurnos:
    def __init__(self, filas):
        self._filas = filas
        self.ultimo_query = None

    def leer(self, tabla, select="*", **filtros):
        self.ultimo_query = dict(tabla=tabla, select=select, filtros=filtros)
        return self._filas


def test_toma_el_aforo_mas_reciente_por_suerte():
    # ya vienen ordenados por fecha desc (como los devuelve PostgREST)
    sb = FakeTurnos([
        {"suerte": "3106-160", "date": "2026-08-01", "tch_pesos": 118.0},
        {"suerte": "3106-160", "date": "2026-05-01", "tch_pesos": 110.0},  # más viejo → se ignora
        {"suerte": "3102-110", "date": "2026-07-15", "tch_pesos": 130.0},
    ])
    v = aforos_vigentes(sb, "2026-09-09")
    assert v == {"3106-160": 118.0, "3102-110": 130.0}


def test_pide_solo_aforos_anteriores():
    sb = FakeTurnos([])
    aforos_vigentes(sb, "2026-09-09")
    fl = sb.ultimo_query["filtros"]
    assert fl["date"] == "lt.2026-09-09"          # disciplina temporal
    assert fl["order"] == "date.desc"


def test_ignora_filas_sin_tch():
    sb = FakeTurnos([{"suerte": "3106-160", "date": "2026-08-01", "tch_pesos": None}])
    assert aforos_vigentes(sb, "2026-09-09") == {}


def test_usa_promedio_de_los_tres_metodos():
    # con los 3 métodos y sin columna de promedio → promedia los tres
    sb = FakeTurnos([{"suerte": "3106-160", "date": "2026-08-01",
                      "tch_diametro": 90.0, "tch_dia12m": 100.0, "tch_pesos": 110.0}])
    assert aforos_vigentes(sb, "2026-09-09") == {"3106-160": 100.0}


def test_prefiere_columna_promedio_si_existe():
    sb = FakeTurnos([{"suerte": "3106-160", "date": "2026-08-01",
                      "tch_promedio": 94.0, "tch_pesos": 110.0}])
    assert aforos_vigentes(sb, "2026-09-09") == {"3106-160": 94.0}
