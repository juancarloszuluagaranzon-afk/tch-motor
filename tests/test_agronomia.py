from tchmotor.agronomia import parse_zona, map_variedad, cargar_var_map


def test_parse_zona_valida():
    assert parse_zona("6H1") == (6, 1)
    assert parse_zona("15H3") == (15, 3)
    assert parse_zona("30H0") == (30, 0)


def test_parse_zona_basura_es_none():
    assert parse_zona("CAÑA") == (None, None)
    assert parse_zona("") == (None, None)
    assert parse_zona(None) == (None, None)
    assert parse_zona("6H9") == (None, None)  # humedad fuera de 0-5


def test_map_variedad_traduce_codigo_interno():
    vm = {"V82": "CC 01-1940", "V39": "CC 85-92"}
    assert map_variedad("V82", vm) == "CC 01-1940"
    assert map_variedad(" V39 ", vm) == "CC 85-92"


def test_map_variedad_deja_pasar_lo_no_mapeado():
    assert map_variedad("CC 05-430", {}) == "CC 05-430"
    assert map_variedad(None, {}) is None


def test_var_map_del_paquete_carga():
    vm = cargar_var_map()
    assert vm["V82"] == "CC 01-1940"
    assert vm["V102"] == "CC 05-430"
    assert len(vm) >= 100
