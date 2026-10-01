from datetime import date

import numpy as np
import pandas as pd

from tchmotor.produccion import (RECAL_MIN, ciclos_activos, cosechas_recientes, factor_campana, leer_maestro_csv,
                                 mes_vigente)

HOY = date(2026, 9, 27)
T_NOW = mes_vigente(HOY)
CICLOS = pd.DataFrame({"sec_ste": ["A", "A", "A"], "planta": ["riopaila"] * 3, "anio": [2023, 2024, 2025],
                       "edad": [12.0, 13.0, 14.0], "t_cos": [2023 * 12 + 5, 2024 * 12 + 6, 2025 * 12 + 8],
                       "harvest": ["2023-06-15", "2024-07-15", "2025-09-15"], "corte": [1, 2, 3]})


def _m(**kw):
    base = {"uso": "CAÑA", "variedad": "CC 01-1940", "numero_corte": 4, "area_neta_ha": 10.0,
            "fecha_ultimo_corte": "2026-01-15", "fecha_proximo_corte": "2027-01-15", "planta": "riopaila"}
    return {**base, **kw}


def test_mes_vigente_usa_el_mes_en_curso_desde_el_dia_20():
    assert mes_vigente(date(2026, 9, 27)) == 2026 * 12 + 8
    assert mes_vigente(date(2026, 10, 2)) == 2026 * 12 + 8


def test_ciclo_en_curso_con_edad_esperada_del_maestro():
    a, fuera = ciclos_activos({"A": _m()}, CICLOS, T_NOW, HOY)
    r = a.iloc[0]
    assert r._obs == 8  # 8,3 meses desde el corte → curva hasta el mes 8
    assert abs(r.edad - 12.0) < 0.1 and r.anio == 2027 and r.mes == 1
    assert r.corte == 4 and np.isnan(r.tch) and r.key == "A|en curso"


def test_sin_proximo_corte_usa_la_edad_tipica_de_la_suerte():
    a, _ = ciclos_activos({"A": _m(fecha_proximo_corte=None)}, CICLOS, T_NOW, HOY)
    assert a.iloc[0].edad == 13.0  # mediana de 12, 13, 14


def test_cana_pasada_de_edad_usa_la_curva_completa_hasta_hoy():
    a, _ = ciclos_activos({"B": _m(fecha_ultimo_corte="2025-06-01", fecha_proximo_corte="2026-06-01")},
                          CICLOS, T_NOW, HOY)
    r = a.iloc[0]
    assert r._obs is None and r.t_cos == T_NOW and r.edad > 15


def test_maestro_atrasado_toma_la_ultima_cosecha_registrada():
    # el maestro dice último corte 2024-07 pero el ZQM ya trae la cosecha de 2025-09 (soca 3)
    a, _ = ciclos_activos({"A": _m(fecha_ultimo_corte="2024-07-10", numero_corte=3)}, CICLOS, T_NOW, HOY)
    r = a.iloc[0]
    assert r.cut == "2025-09-15" and r.corte == 4


def test_maestro_que_ya_cuenta_el_corte_manda_sobre_la_fecha_del_zqm():
    # 3110-081: el ZQM trae la cosecha de corte 3 con fecha 2025-09-15 y el maestro ya la registró
    # (crece la soca 4) con fecha 2025-08-01: manda el maestro
    a, _ = ciclos_activos({"A": _m(fecha_ultimo_corte="2025-08-01", fecha_proximo_corte="2026-08-01")},
                          CICLOS, T_NOW, HOY)
    assert a.iloc[0].cut == "2025-08-01" and a.iloc[0].corte == 4


def test_plantilla_cuenta_la_edad_desde_la_siembra():
    # renovada: el último corte (2025-09-15, también en el ZQM) es la cosecha de antes de sembrar
    a, _ = ciclos_activos({"A": _m(fecha_ultimo_corte="2025-09-15", fecha_siembra="2026-02-25",
                                   numero_corte=1, fecha_proximo_corte="2027-02-25")}, CICLOS, T_NOW, HOY)
    r = a.iloc[0]
    assert r.cut == "2026-02-25" and r.corte == 1 and 7.0 < r._edad_hoy < 7.2


def test_plantilla_de_menos_de_4_meses_no_se_estima():
    a, fuera = ciclos_activos({"A": _m(fecha_ultimo_corte="2025-09-15", fecha_siembra="2026-08-28", numero_corte=1)},
                              CICLOS, T_NOW, HOY)
    assert len(a) == 0 and fuera["muy joven (< 4 meses)"] == 1


def test_lee_el_maestro_csv_oficial():
    texto = ("﻿SUERTE;ZONA;AREA NETA HA;EDAD HOY MESES;Zona Agroecologica;VARIEDAD;USO DE LA SUERTE;"
             "FECHA DE SIEMBRA;FECHA DE ULTIMO CORTE;NUMERO DE CORTE;FECHA DEL PROXIMO CORTE;EMPRESA\n"
             "2101-010;1;2.08;0.82;6H1;CC 09-066;CAÑA;9/07/2024;5/09/2026;3;20/09/2027;CAST\n"
             "3501-230;5;7.5;7.1;11H1;CC 11-0132;CAÑA;25/02/2026;15/03/2025;1;25/02/2027;RIOP\n"
             "9999-001;1;1.0;0;;MANGO;OTROS CULTIVOS;1/01/2020;1/01/2020;1;1/01/2021;BENG\n")
    m = leer_maestro_csv(texto)
    assert set(m) == {"2101-010", "3501-230"}  # BENG no es de Riopaila ni de Castilla
    c = m["2101-010"]
    assert c["planta"] == "castilla" and c["fecha_ultimo_corte"] == "2026-09-05" and c["numero_corte"] == 3
    assert c["area_neta_ha"] == 2.08 and c["uso"] == "CAÑA" and c["zona_agroecologica"] == "6H1"
    assert m["3501-230"]["planta"] == "riopaila" and m["3501-230"]["fecha_siembra"] == "2026-02-25"


def test_cosechas_recientes_completan_lo_que_falta_en_el_zqm():
    maestro = {"A": _m(fecha_ultimo_corte="2025-09-20", numero_corte=4, fecha_siembra="2020-01-01"),
               "B": _m(fecha_ultimo_corte="2026-09-05", numero_corte=2, fecha_siembra="2025-08-01"),
               "C": _m()}
    tabla = pd.DataFrame({"sec_ste": ["A", "B", "A", "Z"], "tch": [110.0, 95.0, 120.0, 100.0],
                          "fecha": [date(2026, 9, 10), date(2026, 9, 3), date(2025, 10, 1), date(2026, 9, 1)]})
    n, fuera = cosechas_recientes(tabla, maestro, CICLOS)
    a = n[n.sec_ste == "A"].iloc[0]
    assert a.cut == "2025-09-20" and a.corte == 4  # el maestro aún no registra esta cosecha
    assert 11 < a.edad < 12 and a.harvest == "2026-09-10" and a.key == "A|2026|9|4"
    b = n[n.sec_ste == "B"].iloc[0]
    assert b.cut == "2025-08-01" and b.corte == 1  # el maestro ya la registró: soca = creciendo − 1
    assert fuera["ya está en el ZQM"] == 1 and fuera["no está en el maestro"] == 1


def test_cosecha_de_suerte_renovada_conserva_su_soca():
    # el maestro ya registró la cosecha de sep-2026 y, como se renueva, volvió a corte 1:
    # la soca cosechada es la del ZQM anterior (corte 3, 2025-09-15) + 1, no 0
    maestro = {"A": _m(fecha_ultimo_corte="2026-09-10", numero_corte=1, fecha_siembra="2020-01-01")}
    tabla = pd.DataFrame({"sec_ste": ["A"], "tch": [90.0], "fecha": [date(2026, 9, 10)]})
    n, _ = cosechas_recientes(tabla, maestro, CICLOS)
    assert n.iloc[0].corte == 4 and n.iloc[0].cut == "2025-09-15"


def test_descarta_lo_que_no_se_puede_estimar():
    m = {"joven": _m(fecha_ultimo_corte="2026-07-01"), "reno": _m(variedad="RENOVACION"),
         "pasto": _m(uso="PASTO"), "sin": _m(fecha_ultimo_corte=None)}
    a, fuera = ciclos_activos(m, CICLOS, T_NOW, HOY)
    assert len(a) == 0 and sum(fuera.values()) == 4


def test_varias_se_estima_como_una_variedad_mas():
    a, fuera = ciclos_activos({"V": _m(variedad="VARIAS"), "R": _m(variedad="RENOVACION")}, CICLOS, T_NOW, HOY)
    assert list(a.sec_ste) == ["V"] and a.iloc[0].variedad == "VARIAS"
    assert fuera["sin variedad estimable"] == 1


class _Motor:
    def predecir(self, X):
        return np.full(len(X), 100.0)


def test_factor_solo_aplica_con_suficientes_cosechas_cerradas():
    n = RECAL_MIN
    hist = pd.DataFrame({"_anio": [2026] * (n + 3), "_obs": ["completo"] * (n + 3),
                         "_planta": ["riopaila"] * n + ["castilla"] * 3, "_tch": [90.0] * (n + 3),
                         "_ha": [1.0] * (n + 3), "edad": [12.0] * (n + 3)})
    f, _ = factor_campana(_Motor(), hist, 2026)
    assert f["riopaila"]["factor"] == 0.9 and f["riopaila"]["aplica"]
    assert f["castilla"]["factor"] == 1.0 and not f["castilla"]["aplica"]
    assert f["riopaila"]["sesgo_modelo_pct"] == 11.1


def test_reales_trae_variedad_edad_y_modelo_sin_factor():
    from tchmotor.produccion import reales
    cerr = pd.DataFrame({"_sec": ["A", "A", "B"], "_planta": ["riopaila"] * 3, "_anio": [2026] * 3, "_mes": [3, 8, 5],
                         "corte": [2.0, 3.0, np.nan], "variedad": ["CC 01-1940", "CC 01-1940", "VARIAS"],
                         "edad": [12.04, 12.5, 13.0], "_tch": [110.0, 120.0, 95.0], "_ha": [10.0, 10.0, 5.0],
                         "pred": [118.26, 121.0, 99.9], "_tipo": ["Mecanico", None, "Manual"]})
    r = {x["sec_ste"]: x for x in reales(cerr, 2026)}
    assert r["A"]["mes"] == 8 and r["A"]["corte"] == 3 and r["A"]["tipo_cosecha"] is None  # la cosecha más reciente
    assert r["A"]["variedad"] == "CC 01-1940" and r["A"]["edad_meses"] == 12.5 and r["A"]["anio"] == 2026
    assert r["B"]["corte"] is None and r["B"]["tch_modelo"] == 99.9 and r["B"]["tch_real"] == 95.0
