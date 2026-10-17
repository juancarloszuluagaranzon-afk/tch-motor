import math

import numpy as np
import pandas as pd

from tchmotor.aforo import AforoSintetico
from tchmotor.dataset_gee import construir, cortes_zqm, historia_tch, plantios, previa, rasgos, rasgos_clima

SINT = AforoSintetico([{"variedad": "CC 01-1940", "soca": 2, "pob": 10.0, "peso": 1.4, "dia": 2.7, "tch": 110}] * 4)


def _ciclos(tchs, anios, sec="3102-010", edad=12.0):
    filas = []
    for tch, anio in zip(tchs, anios):
        filas.append({"sec_ste": sec, "planta": "riopaila", "anio": anio, "mes": 6, "corte": 2,
                      "variedad": "CC 01-1940", "ha": 5.0, "edad": edad, "tch": tch, "tipo_cosecha": "Manual",
                      "t_cos": anio * 12 + 5, "t_cut": anio * 12 + 5 - int(round(edad)),
                      "harvest": f"{anio}-06-15", "cut": f"{anio - 1}-06-15", "key": f"{sec}|{anio}"})
    return pd.DataFrame(filas)


def test_historia_usa_solo_ciclos_anteriores():
    h = historia_tch(_ciclos([100, 120, 140, 80], [2020, 2021, 2022, 2023]))
    assert math.isnan(h.prev_tch1[0])
    assert h.prev_tch1.tolist()[1:] == [100, 120, 140]
    assert h.prev_tch3[3] == (100 + 120 + 140) / 3  # el 80 propio nunca entra
    assert h.prev_n.tolist() == [0, 1, 2, 3]


def test_previa_excluye_el_actual_y_el_futuro():
    v = pd.Series([0.5, np.nan, 0.7, 0.9])
    g = pd.Series(["a", "a", "a", "a"])
    p = previa(v, g)
    assert math.isnan(p[0])
    assert p[1] == 0.5 and p[2] == 0.5
    assert abs(p[3] - 0.6) < 1e-12


def test_calor_solo_usa_meses_ya_transcurridos():
    clima = {("riopaila", "3102-010", t): float(t - 100) for t in range(100, 115)}
    clima[("riopaila", None, 120)] = 9.0  # respaldo de planta
    f = rasgos_clima(clima, "riopaila", "3102-010", t_cut=100, t_obs=106)
    assert f["clima_tmax60"] == (5 + 6) / 2  # meses 105 y 106, nunca 107 en adelante
    assert f["clima_tmax_ciclo"] == np.mean(range(1, 7))
    g = rasgos_clima(clima, "riopaila", "sin-geo", t_cut=110, t_obs=120)
    assert g["clima_tmax60"] == 9.0  # sin dato de la suerte: usa la planta


def test_tipo_de_cosecha_anterior_viene_del_ciclo_previo():
    c = _ciclos([100, 120, 140], [2022, 2023, 2024])
    c["tipo_cosecha"] = ["Mecanico", "Manual", "Mecanico"]
    meses = [{"planta": "riopaila", "sec_ste": "3102-010", "anio": t // 12, "mes": t % 12 + 1, "t": t,
              "NDVI": 0.5, "NDMI": 0.1, "EVI": 0.3, "NDRE": 0.2} for t in range(2021 * 12, 2024 * 12 + 6)]
    d = construir(c, pd.DataFrame(meses), SINT, {}, {}, edades_obs=(None,), desde=2020)
    assert d.tipo_mec.tolist() == [1.0, 0.0, 1.0]
    assert math.isnan(d.prev_mec.iloc[0]) and d.prev_mec.tolist()[1:] == [1.0, 0.0]
    assert "tipo_mec" not in rasgos(d, quitar=("tipo_actual",)).columns
    assert "prev_mec" in rasgos(d, quitar=("tipo_actual",)).columns


def test_cortes_une_meses_consecutivos_de_una_cosecha():
    zqm = pd.DataFrame({
        "AÑO": [2024, 2024, 2025], "Mes": [5, 6, 6], "Ubic Técnica": ["3102-010"] * 3,
        "Empresa": ["03 RIOPAILA"] * 3, "Corte": [2, 2, 3], "Variedad Principal": ["CC 01-1940"] * 3,
        "Area": [10.0, 10.0, 10.0], "Edad": [12.0, 12.1, 12.0], "TC-mes": [400, 800, 1100],
        "TC-Total": [400, 1200, 1100], "Tipo Cosecha": ["Manual"] * 3,
    })
    c = cortes_zqm(zqm)
    assert len(c) == 2
    assert c.tch.tolist() == [120.0, 110.0]  # toma el acumulado (1200 t / 10 ha)
    assert c.mes.tolist() == [6, 6]


def test_edad_de_observacion_no_ve_meses_futuros():
    c = _ciclos([100, 120], [2023, 2024])
    meses = []
    for _, r in c.iterrows():
        for a in range(0, 13):
            t = r.t_cut + a
            meses.append({"planta": "riopaila", "sec_ste": r.sec_ste, "anio": t // 12, "mes": t % 12 + 1,
                          "t": t, "NDVI": 0.2 + 0.05 * a, "NDMI": 0.1, "EVI": 0.3, "NDRE": 0.2})
    # el mes del corte es el último del ciclo anterior y el primero del nuevo: la tabla real
    # trae una sola fila por suerte y mes
    m = pd.DataFrame(meses).drop_duplicates(["sec_ste", "t"], keep="last")
    d = construir(c, m, SINT, {}, {}, edades_obs=(6, None), desde=2020)
    joven = d[d._obs == "6 meses"]
    completo = d[d._obs == "completo"]
    assert (joven.ndvi_n <= 7).all() and (completo.ndvi_n >= 12).all()
    assert (joven.ndvi_peak.values < completo.ndvi_peak.values).all()
    assert math.isnan(joven.iloc[0]["anom_ndvi_e5_8"])  # primer ciclo: sin historia de dosel
    assert abs(joven.iloc[1]["anom_ndvi_e5_8"]) < 1e-9  # mismo dosel que el ciclo anterior
    r = completo.iloc[1]
    assert abs(r["anom_dif_e5_8"] - (r["anom_ndmi_e5_8"] - r["anom_ndvi_e5_8"])) < 1e-12
    assert "anom_ndvi_e9_11" not in joven.columns or joven["anom_ndvi_e9_11"].isna().all()
    assert "prev_tch1" not in rasgos(d, quitar=("historia",)).columns
    assert "hist_pob" in rasgos(d, quitar=("historia",)).columns  # aforo sintético se queda


def test_plantio_nuevo_cuando_baja_el_corte_o_cambia_la_variedad():
    c = _ciclos([100, 110, 120, 130, 140, 150], [2019, 2020, 2021, 2022, 2023, 2024])
    c["corte"] = [4, 5, 1, 2, 3, np.nan]  # renovada en 2021; el último sin número de corte
    c["variedad"] = ["CC 85-92", "CC 85-92", "CC 05-430", "VARIAS", "CC 05-430", "CC 05-430"]
    assert plantios(c, {}).tolist() == ["3102-010#1"] * 2 + ["3102-010#2"] * 4  # VARIAS y NaN no renuevan
    c.loc[3:5, "variedad"] = ["CC 05-430", "CC 01-1940", "CC 01-1940"]  # cambia la variedad sin bajar el corte
    assert plantios(c, {}).tolist()[3:] == ["3102-010#2", "3102-010#3", "3102-010#3"]


def test_historia_del_plantio_no_mezcla_la_variedad_vieja():
    c = _ciclos([160, 100, 95, 163], [2021, 2022, 2023, 2024])
    c["corte"] = [3, 4, 5, 1]
    c["variedad"] = ["CC 85-92"] * 3 + ["CC 05-430"]
    c = pd.concat([c, _ciclos([145], [2025]).assign(corte=2, variedad="CC 05-430")], ignore_index=True)
    meses = []
    for _, r in c.iterrows():
        for a in range(0, 13):
            t = r.t_cut + a
            v = 0.3 if r.anio == 2025 else 0.4  # el ciclo de 2025 con dosel 25 % más débil
            meses.append({"planta": "riopaila", "sec_ste": r.sec_ste, "anio": t // 12, "mes": t % 12 + 1,
                          "t": t, "NDVI": v, "NDMI": v, "EVI": v, "NDRE": 0.2})
    m = pd.DataFrame(meses).drop_duplicates(["sec_ste", "t"], keep="last")
    d = construir(c, m, SINT, {}, {}, edades_obs=(None,), desde=2020).set_index("_anio")
    assert d.loc[2025, "prev_tch1_p"] == 163 and d.loc[2025, "prev_n_p"] == 1
    assert d.loc[2025, "prev_tch3"] == (100 + 95 + 163) / 3  # la de la suerte sí mezcla
    assert math.isnan(d.loc[2024, "prev_tch1_p"])  # la plantilla no tiene historia en su plantío
    assert abs(d.loc[2025, "anoml_ndmi_e5_8"] + 0.1) < 1e-9
    assert abs(d.loc[2025, "analog_ndmi_e5_8"] - 163 * 0.75) < 1e-9
    assert not [k for k in rasgos(d, quitar=("plantio",)).columns if k.startswith(("anomp_", "anoml_", "analog_"))]
    assert "prev_tch1_p" not in rasgos(d, quitar=("plantio",)).columns
    assert "prev_tch1" in rasgos(d, quitar=("plantio",)).columns
