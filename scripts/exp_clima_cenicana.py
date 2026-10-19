# -*- coding: utf-8 -*-
"""Experimento: ¿el clima de la red de Cenicaña mejora el estimado?

Clima mensual por zona (promedio de estaciones), desde el Excel consolidado del Meteoportal
(Clima_Cenicana_Riopaila_Castilla_1993-2026.xlsx):
  Riopaila: La Paila, Zarzal, Paila Arriba, Bugalagrande (las que rodean las suertes, lat 4,25-4,37)
  Castilla: Pradera, Florida, Candelaria, El Tiple, Cenicaña, Miranda (lat 3,06-3,44)
Rasgos por ciclo, solo con los meses ya vividos a la edad de observación (sin mirar el futuro): radiación,
balance hídrico (lluvia − evaporación), lluvia, evaporación, grados-día, temperaturas y humedad, en el arranque
(meses 1-4), el gran crecimiento (5-8) y los últimos 3 meses observados, como anomalía frente al promedio
1994-2018 del mismo mes en la zona.

Se compara el motor de producción (ee-1.1) contra el mismo + clima, fuera de muestra por año, a ciclo completo y
a 8 meses, en total, por planta, en las suertes de 150 t/ha o más y en el sesgo del año (sin factor de campaña).
No toca producción.

Uso:  .venv-gee\\Scripts\\python.exe scripts\\exp_clima_cenicana.py "<ruta del Excel de clima>" [--arboles 300]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402
import openpyxl  # noqa: E402
import pandas as pd  # noqa: E402

from tchmotor import AforoSintetico, MotorTCH, cargar_var_map, rutas  # noqa: E402
from tchmotor import dataset_gee as dg  # noqa: E402
from tchmotor import produccion as pr  # noqa: E402
from tchmotor.aforo import registros_aforo_excel  # noqa: E402

ZONAS = {"riopaila": ["PAI", "ZAR", "PAR", "BLG"], "castilla": ["PRA", "FLO", "CAN", "TIP", "CEN", "MIR"]}
VARS = {  # columna del Excel -> nombre corto
    "Radiación solar (cal/cm² por día)": "rad",
    "Condición hídrica (lluvia − evaporación) (mm)": "bh",
    "Precipitación (mm)": "lluvia",
    "Evaporación (mm)": "evap",
    "Grados-día (°C·día por día)": "gd",
    "Temperatura máxima media (°C)": "tmax",
    "Temperatura mínima media (°C)": "tmin",
    "Humedad relativa (%)": "hr",
}
SUMA = {"bh", "lluvia", "evap"}  # se acumulan; el resto se promedia
ESCENARIOS = [("2025", 2024, 2025), ("2026", 2025, 2026), ("2026 · entrenado hasta 2024", 2024, 2026)]


def clima_por_zona(ruta):
    """{(zona, t): {var: valor}} con t = año·12 + mes − 1, promedio de las estaciones de la zona con dato,
    y la anomalía frente al promedio 1994-2018 del mismo mes."""
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    filas = list(wb["Mensual"].iter_rows(values_only=True))
    enc = filas[0]
    d = pd.DataFrame(filas[1:], columns=enc)
    d = d.rename(columns={k: v for k, v in VARS.items()})
    est_zona = {e: z for z, es in ZONAS.items() for e in es}
    d["zona"] = d["Código"].map(est_zona)
    d = d[d.zona.notna()]
    d["t"] = d["Año"] * 12 + d["Mes"] - 1
    z = d.groupby(["zona", "t", "Año", "Mes"])[list(VARS.values())].mean().reset_index()
    normal = z[z["Año"].between(1994, 2018)].groupby(["zona", "Mes"])[list(VARS.values())].mean()
    an = z.join(normal, on=["zona", "Mes"], rsuffix="_n")
    for v in VARS.values():
        an[f"{v}_a"] = an[v] - an[f"{v}_n"]
    return {(r.zona, int(r.t)): {f"{v}_a": getattr(r, f"{v}_a") for v in VARS.values()} for r in an.itertuples()}


def rasgos_clima(fila, clima):
    """Rasgos de clima de un ciclo con los meses ya vividos: arranque 1-4, crecimiento 5-8, últimos 3 observados."""
    t_cos = int(fila["_anio"]) * 12 + int(fila["_mes"]) - 1
    t_cut = t_cos - int(round(fila["edad"]))
    a_max = int(round(fila["edad"])) if fila["_obs"] == "completo" else int(fila["_obs"].split()[0])
    out = {}
    tramos = {"ini": range(1, 5), "crec": range(5, 9), "fin": range(max(1, a_max - 2), a_max + 1)}
    for nombre, meses in tramos.items():
        vals = [clima.get((fila["_planta"], t_cut + a)) for a in meses if a <= a_max]
        vals = [v for v in vals if v]
        for v in VARS.values():
            xs = [x[f"{v}_a"] for x in vals if x.get(f"{v}_a") is not None and x[f"{v}_a"] == x[f"{v}_a"]]
            out[f"clc_{nombre}_{v}"] = (sum(xs) if v in SUMA else np.mean(xs)) if xs else np.nan
    return out


def metricas(g, col, k=None):
    pred = g[col] * (1 if k is None else k)
    e = (pred - g._tch) / g._tch
    return {"n": len(g), "mape": 100 * e.abs().mean(), "sesgo": 100 * ((pred * g._ha).sum() / (g._tch * g._ha).sum() - 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clima")
    ap.add_argument("--arboles", type=int, default=300)
    a = ap.parse_args()
    t0 = time.time()
    clima = clima_por_zona(a.clima)
    print(f"clima: {len(clima)} meses-zona · {time.time() - t0:.0f} s", flush=True)
    vm = cargar_var_map()
    sint = AforoSintetico(registros_aforo_excel(str(rutas.BASE_AFOROS)), min_n=4)
    c = dg.cortes_zqm(dg.leer_zqm())
    maestro, _ = pr.cargar_maestro()
    rec, _ = pr.cosechas_recientes(pr.leer_cosechas_recientes(), maestro, c)
    c = pd.concat([c, rec], ignore_index=True).drop_duplicates("key")
    zonas = {**dg.zonas_maestro(), **{s: v["zona_agroecologica"] for s, v in maestro.items() if v["zona_agroecologica"]}}
    d = dg.construir(c, dg.cargar_mensual(), sint, vm, zonas)
    cl =pd.DataFrame([rasgos_clima(f, clima) for f in d[["_anio", "_mes", "edad", "_obs", "_planta"]].to_dict("records")])
    d = pd.concat([d, cl], axis=1)
    base = list(dg.rasgos(d, pr.QUITAR).columns.drop([c_ for c_ in cl.columns if c_ in d.columns], errors="ignore"))
    base = [c_ for c_ in base if not c_.startswith("clc_")]
    con = base + list(cl.columns)
    print(f"dataset {len(d)} filas · rasgos base {len(base)} · con clima {len(con)} · cobertura clima "
          f"{100 * cl.notna().mean().mean():.0f} % · {time.time() - t0:.0f} s", flush=True)
    preds = []
    for nombre, hasta, prueba in ESCENARIOS:
        tr, te = d[d._anio.between(2019, hasta)], d[d._anio == prueba].copy()
        te["escenario"] = nombre
        for var, cols in (("base", base), ("clima", con)):
            m = MotorTCH(n_estimators=a.arboles).entrenar(tr[cols], tr._tch.values)
            te[var] = m.predecir(te[cols])
            if var == "clima" and nombre == "2026":
                imp = pd.Series(m.rf_.feature_importances_, index=m.cols_)
                top = imp[imp.index.str.startswith("clc_")].sort_values(ascending=False)
                print(f"  peso total del clima en el modelo: {100 * top.sum():.1f} % · más usados: "
                      + ", ".join(f"{k} {100 * v:.1f}%" for k, v in top.head(6).items()), flush=True)
        print(f"  {nombre} listo · {time.time() - t0:.0f} s", flush=True)
        preds.append(te)
    p = pd.concat(preds, ignore_index=True)
    p.to_pickle(rutas.GEE_DIR / "exp_clima_cenicana_pred.pkl")
    print("\n==== error por suerte (MAPE) y sesgo del total, SIN factor de campaña ====")
    for obs in ("completo", "8 meses", "6 meses"):
        q = p[p._obs == obs]
        if not len(q):
            continue
        print(f"-- {obs}")
        for esc, g in q.groupby("escenario", sort=False):
            for etiqueta, h in (("todas", g), ("riopaila", g[g._planta == "riopaila"]), ("castilla", g[g._planta == "castilla"]),
                                ("real ≥ 150", g[g._tch >= 150]), ("real < 90", g[g._tch < 90])):
                if len(h) < 10:
                    continue
                b, k = metricas(h, "base"), metricas(h, "clima")
                print(f"  {esc:28s} {etiqueta:11s} n={b['n']:4d} · MAPE {b['mape']:5.1f} → {k['mape']:5.1f} · "
                      f"sesgo {b['sesgo']:+5.1f} → {k['sesgo']:+5.1f}")
    print(f"\ntotal {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
