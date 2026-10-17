# -*- coding: utf-8 -*-
"""Experimento: historia de la suerte desde su última siembra (plantío) y comparación con el ciclo anterior.

Hoy los rasgos de historia (prev_tch1/3, prev_tchm3) y las anomalías del dosel se calculan con TODOS los ciclos
anteriores de la suerte, aunque haya habido renovación y cambio de variedad de por medio. Caso que lo destapó:
3425-020 (renovada en 2024 con CC 05-430, plantilla 163,4): el motor estimó 121 = promedio de 163, 103 y 97, estos
dos de la variedad vieja; el real fue 145.

Variantes (mismas filas, mismo Random Forest, validación fuera de muestra por año como entrenar_gee.py):
  base  motor actual (rasgos de la variante «nuevo»: sin clima ni tipo de cosecha)
  B     historia y anomalías solo dentro del plantío actual (reemplazan a las de la suerte)
  C     base + historia y anomalías del plantío (el modelo elige)
  D     C + comparación con el ciclo anterior del plantío en las mismas edades (diferencia y
        «análogo» = TCH del ciclo anterior × cuánto cambió el dosel)
Un plantío nuevo empieza cuando el número de corte baja respecto al ciclo anterior o cambia la variedad.

No toca producción. Uso:  .venv-gee\\Scripts\\python.exe scripts\\exp_historia_plantio.py [--arboles 300]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from tchmotor import AforoSintetico, MotorTCH, cargar_var_map, rutas  # noqa: E402
from tchmotor import dataset_gee as dg  # noqa: E402
from tchmotor import produccion as pr  # noqa: E402
from tchmotor.agronomia import map_variedad  # noqa: E402
from tchmotor.aforo import registros_aforo_excel  # noqa: E402
from tchmotor.features import build_features  # noqa: E402

ESCENARIOS = [("2025", 2024, 2025), ("2026", 2025, 2026), ("2026 · entrenado hasta 2024", 2024, 2026)]
NUEVOS = ("prev_tch1_p", "prev_tch3_p", "prev_tchm3_p", "prev_n_p")
MALAS = {"", "VARIAS", "RENOVACION", "NAN", "NONE"}


def plantios(c, vm):
    var = c.variedad.map(lambda v: (map_variedad(v, vm) or str(v) or "").strip().upper())
    prev_c = c.groupby("sec_ste").corte.shift(1)
    prev_v = var.groupby(c.sec_ste).shift(1)
    cambio_var = prev_v.notna() & (var != prev_v) & ~var.isin(MALAS) & ~prev_v.isin(MALAS)
    nuevo = prev_c.isna() | (c.corte < prev_c) | cambio_var
    n_pl = nuevo.astype(int).groupby(c.sec_ste).cumsum()
    clave = c.sec_ste + "#" + n_pl.astype(str)
    return clave, c.groupby(clave).cumcount() + 1, n_pl, (nuevo & prev_c.notna()).sum()


def construir(c, m, sint, vm, zonas, desde=2019, min_puntos=3):
    c = c.sort_values(["sec_ste", "t_cos"]).reset_index(drop=True)
    pl, n_en_pl, n_pl, n_renov = plantios(c, vm)
    print(f"renovaciones detectadas en la historia: {n_renov} · ciclos {len(c)}", flush=True)
    mec = c["tipo_cosecha"].map({"Mecanico": 1.0, "Manual": 0.0})
    tipo = pd.DataFrame({"tipo_mec": mec, "prev_mec": mec.groupby(c["sec_ste"]).shift(1)}).to_dict("records")
    H = dg.historia_tch(c).to_dict("records")
    Hp = dg.historia_tch(c.assign(sec_ste=pl)).add_suffix("_p").to_dict("records")
    L = dg.dosel_por_edad(c, m)
    curvas = {i: {idx: [{"from": dg._mes_iso(t), "mean": float(v)} for t, v in zip(g.t, g[idx]) if pd.notna(v)]
                  for idx in dg.INDICES_CURVA} for i, g in L.groupby("i")}
    prev_tch1_p = pd.Series([h["prev_tch1_p"] for h in Hp])
    filas = []
    for obs in dg.EDADES_OBS:
        T = dg.medias_tramo(L, len(c), obs)
        A = pd.DataFrame({f"anom_{k}": T[k] - dg.previa(T[k], c["sec_ste"]) for k in T.columns}, index=T.index)
        Ap = pd.DataFrame({f"anomp_{k}": T[k] - dg.previa(T[k], pl) for k in T.columns}, index=T.index)
        Al = pd.DataFrame({f"anoml_{k}": T[k] - T[k].groupby(pl).shift(1) for k in T.columns}, index=T.index)
        for t in dg.TRAMOS:
            if f"anom_ndmi_{t}" in A:
                A[f"anom_dif_{t}"] = A[f"anom_ndmi_{t}"] - A[f"anom_ndvi_{t}"]
                Ap[f"anomp_dif_{t}"] = Ap[f"anomp_ndmi_{t}"] - Ap[f"anomp_ndvi_{t}"]
        An = pd.DataFrame(index=T.index)
        for k in ("ndmi_e5_8", "evi_e5_8", "ndvi_e5_8", "ndmi_e9_11", "evi_e9_11"):
            if k in T:
                ant = T[k].groupby(pl).shift(1)
                razon = (T[k] / ant).where(ant.abs() > 0.05).clip(0.5, 1.5)
                An[f"analog_{k}"] = prev_tch1_p * razon
        # con caña joven puede no haber ningún tramo comparable: to_dict de un DataFrame sin columnas da []
        A, Ap, Al, An = (x.to_dict("records") if x.shape[1] else [{}] * len(c) for x in (A, Ap, Al, An))
        for i, r in enumerate(c.itertuples(index=False)):
            if r.anio < desde or (obs is not None and obs >= r.edad - 0.5):
                continue
            reg = {"variedad": r.variedad, "corte": r.corte, "edad": r.edad, "mes": r.mes, "ha": r.ha,
                   "zona_agro": zonas.get(r.sec_ste), "cut": r.cut, "curves": curvas.get(i, {})}
            f = build_features(reg, sint, vm, max_age=obs, indices=dg.INDICES_CURVA)
            if f["ndvi_n"] < min_puntos:
                continue
            f.pop("aforo_vivo", None)
            f["edad_obs"] = float(r.edad if obs is None else obs)
            f["castilla"] = int(r.planta == "castilla")
            for x in (H[i], Hp[i], A[i], Ap[i], Al[i], An[i], tipo[i]):
                f.update(x)
            f.update(_key=r.key, _sec=r.sec_ste, _planta=r.planta, _anio=r.anio, _mes=r.mes,
                     _obs="completo" if obs is None else f"{obs} meses", _tch=r.tch, _ha=r.ha, _tipo=r.tipo_cosecha,
                     _corte=r.corte, _renov=bool(n_pl[i] > 1 and n_en_pl[i] <= 3))
            filas.append(f)
    return pd.DataFrame(filas)


def columnas(d):
    todas = [c for c in d.columns if not c.startswith("_") and c not in ("tipo_mec", "prev_mec")]
    nuevas = [c for c in todas if c in NUEVOS or c.startswith(("anomp_", "anoml_", "analog_"))]
    base = [c for c in todas if c not in nuevas]
    suerte = ("prev_tch1", "prev_tch3", "prev_tchm3", "prev_n")
    B = [c for c in base if c not in suerte and not c.startswith("anom_")] + \
        [c for c in nuevas if c in NUEVOS or c.startswith("anomp_")]
    C = base + [c for c in nuevas if c in NUEVOS or c.startswith("anomp_")]
    D = C + [c for c in nuevas if c.startswith(("anoml_", "analog_"))]
    return {"base": base, "B": B, "C": C, "D": D}


def metricas(g, col):
    e = g[col] - g._tch
    ape = e.abs() / g._tch
    return pd.Series({"n": len(g), "MAPE": 100 * ape.mean(),
                      "sesgo": 100 * ((g[col] * g._ha).sum() / (g._tch * g._ha).sum() - 1), "±20": 100 * (ape <= 0.2).mean()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arboles", type=int, default=300)
    ap.add_argument("--rapido", action="store_true", help="solo 2026 (entrenado hasta 2025), base contra D, y el "
                                                          "detalle de las cosechas de octubre")
    a = ap.parse_args()
    global ESCENARIOS
    if a.rapido:
        ESCENARIOS = [("2026", 2025, 2026)]
    t0 = time.time()
    vm = cargar_var_map()
    sint = AforoSintetico(registros_aforo_excel(str(rutas.BASE_AFOROS)), min_n=4)
    c = dg.cortes_zqm(dg.leer_zqm())
    maestro, _ = pr.cargar_maestro()
    rec, _ = pr.cosechas_recientes(pr.leer_cosechas_recientes(), maestro, c)
    c = pd.concat([c, rec], ignore_index=True).drop_duplicates("key")
    zonas = {**dg.zonas_maestro(), **{s: v["zona_agroecologica"] for s, v in maestro.items() if v["zona_agroecologica"]}}
    d = construir(c, dg.cargar_mensual(), sint, vm, zonas)
    cols = columnas(d)
    if a.rapido:
        cols = {k: cols[k] for k in ("base", "D")}
    print(f"dataset {len(d)} filas · {d._key.nunique()} ciclos · rasgos: " +
          ", ".join(f"{k} {len(v)}" for k, v in cols.items()) + f" · {time.time() - t0:.0f} s", flush=True)
    preds = []
    for nombre, hasta, prueba in ESCENARIOS:
        tr, te = d[d._anio.between(2019, hasta)], d[d._anio == prueba].copy()
        te["escenario"] = nombre
        for var, cc in cols.items():
            t1 = time.time()
            te[var] = MotorTCH(n_estimators=a.arboles).entrenar(tr[cc], tr._tch.values).predecir(te[cc])
            print(f"  {nombre} · {var}: {time.time() - t1:.0f} s", flush=True)
        preds.append(te)
    p = pd.concat(preds, ignore_index=True)
    p.to_pickle(rutas.GEE_DIR / "exp_historia_plantio_pred.pkl")
    pd.set_option("display.width", 200)
    banda = pd.cut(p._corte, [0, 1, 3, 6, 10, 99], labels=["plantilla", "soca 2-3", "soca 4-6", "soca 7-10", "soca 11+"])
    for obs in ("completo", "8 meses"):
        q = p[p._obs == obs]
        print(f"\n==== {obs}: MAPE / sesgo por variante ====")
        for esc, g in q.groupby("escenario", sort=False):
            print(f"  {esc}")
            for etiqueta, h in [("todas", g), ("renovadas (≤3 ciclos del plantío nuevo)", g[g._renov]),
                                ("no renovadas", g[~g._renov])] + [(str(b), g[banda[g.index] == b]) for b in banda.cat.categories]:
                if len(h) < 10:
                    continue
                txt = " · ".join(f"{v} {metricas(h, v)['MAPE']:5.1f}% ({metricas(h, v)['sesgo']:+5.1f})" for v in cols)
                print(f"    {etiqueta:40s} n={len(h):4d}  {txt}")
    caso = p[(p._sec == "3425-020") & (p._obs == "completo") & (p._anio == 2026)]
    for _, x in caso.iterrows():  # itertuples renombra las columnas que empiezan con «_»
        print(f"\n3425-020 ({x['escenario']}): real {x['_tch']:.1f} · " + " · ".join(f"{v} {x[v]:.1f}" for v in cols))
    if a.rapido:
        oc = p[(p._obs == "completo") & (p._anio == 2026) & (p._mes == 10)].copy()
        print(f"\ncosechas de octubre en la prueba: {len(oc)}")
        for etiqueta, g in [("todas", oc), ("renovadas", oc[oc._renov]), ("no renovadas", oc[~oc._renov])]:
            if len(g):
                print(f"  {etiqueta:12s} n={len(g):3d} " + " · ".join(
                    f"{v} {metricas(g, v)['MAPE']:5.1f}% ({metricas(g, v)['sesgo']:+5.1f})" for v in cols))
        for _, x in oc[oc._renov].sort_values("_sec").iterrows():
            print(f"  {x['_sec']} soca {int(x['_corte']):>2} real {x['_tch']:6.1f} · " + " · ".join(f"{v} {x[v]:6.1f}" for v in cols))
    print(f"\ntotal {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
