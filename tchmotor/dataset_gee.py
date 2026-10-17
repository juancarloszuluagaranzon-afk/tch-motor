# -*- coding: utf-8 -*-
"""Dataset de entrenamiento con Earth Engine: tabla mensual por suerte + cosechas del ZQM.

Cada fila es un ciclo cosechado (suerte + soca) visto a una edad de observación
(`edad_obs`): la curva mensual de índices hasta esa edad, la agronomía y el aforo
sintético de siempre, y la HISTORIA PROPIA de la suerte:

* TCH de sus ciclos anteriores (último, media de los últimos 3, TCH por mes de edad).
* Anomalía del dosel: media del índice en un tramo de edad menos la media de ese mismo
  tramo en los ciclos anteriores de la misma suerte. Es la señal que explicó ~70 % del
  cambio de TCH entre cosechas de una misma suerte en Riopaila.
* Lo mismo dentro del PLANTÍO actual (desde la última siembra; sufijo `_p` y prefijo `anomp_`),
  y la comparación con el ciclo inmediatamente anterior del plantío a las mismas edades:
  diferencia del dosel (`anoml_`) y «análogo» = TCH de ese ciclo × cuánto cambió el dosel
  (`analog_`). Una renovación con cambio de variedad deja de mezclar la caña vieja con la
  nueva. Validado fuera de muestra el 16-oct-2026 (scripts/exp_historia_plantio.py, variante D):
  MAPE 2025 9,3→9,1 %, 2026 13,6→13,0 %, 2026 entrenado hasta 2024 12,8→12,4 %.

Lo histórico sale solo de ciclos cosechados antes del que se predice: nada del futuro
entra en los rasgos. Repetir cada ciclo a varias edades de observación (6, 8, 10 meses y
ciclo completo) enseña al modelo a proyectar caña joven con la curva a medias, que es lo
que ve en producción.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import rutas
from .agronomia import map_variedad
from .features import build_features

_RAIZ = rutas.RAIZ
ZQM_HIST = rutas.ZQM_HIST
ZQM_2026 = rutas.ZQM_2026
MENSUAL = rutas.MENSUAL
CLIMA = rutas.CLIMA
CLIMA_BASE = (2011, 2024)  # climatología fija, sin los años que se validan
MAESTROS = rutas.TABLONES_DIR

INDICES_CURVA = ("NDVI", "NDMI", "EVI", "NDRE")
INDICES_ANOM = ("NDVI", "NDMI", "EVI")
TRAMOS = {"e3_4": (3, 4), "e5_8": (5, 8), "e9_11": (9, 11)}
EDADES_OBS = (4, 6, 8, 10, 12, None)  # None = ciclo completo
_DIAS = 30.44
_COLS = ["AÑO", "Mes", "Ubic Técnica", "Empresa", "Corte", "Variedad Principal", "Area", "Edad",
         "TC-mes", "TC-Total", "Tipo Cosecha"]
# columnas de un ciclo (salida de cortes_zqm)
COLS_CICLO = ["sec_ste", "planta", "anio", "mes", "corte", "variedad", "ha", "edad", "tch", "tipo_cosecha",
              "t_cos", "t_cut", "harvest", "cut", "key"]


# ---------------------------------------------------------------- ZQM → ciclos
def _dedup(cols):
    visto, out = {}, []
    for c in cols:
        c = re.sub(r"\s+", " ", str(c)).strip()
        if c in visto:
            visto[c] += 1
            out.append(f"{c}__{visto[c]}")
        else:
            visto[c] = 0
            out.append(c)
    return out


def _hoja(path, fila_encabezado: int) -> pd.DataFrame:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    filas, hdr, vacias = [], None, 0
    for i, r in enumerate(wb.worksheets[0].iter_rows(values_only=True)):
        if i < fila_encabezado:
            continue
        if i == fila_encabezado:
            hdr = [str(x).strip() if x is not None else f"c{j}" for j, x in enumerate(r)]
            continue
        if all(v is None for v in r[:6]):
            vacias += 1
            if vacias > 50:
                break
            continue
        vacias = 0
        filas.append(r)
    wb.close()
    return pd.DataFrame(filas, columns=_dedup(hdr))


def leer_zqm(hist=ZQM_HIST, z26=ZQM_2026) -> pd.DataFrame:
    """Filas mensuales del ZQM histórico (2011-2025) y del ZQM 2026 (encabezado en la fila 10)."""
    partes = [_hoja(hist, 0)]
    if z26 and Path(z26).exists():
        z = _hoja(z26, 9)
        z["AÑO"] = 2026
        partes.append(z)
    for d in partes:
        for k in _COLS:
            if k not in d.columns:
                d[k] = np.nan
    df = pd.concat([d[_COLS] for d in partes], ignore_index=True)
    for c in ["AÑO", "Mes", "Corte", "Area", "Edad", "TC-mes", "TC-Total"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["Ubic Técnica", "Empresa", "Variedad Principal", "Tipo Cosecha"]:
        df[c] = df[c].astype(str).str.strip()
    return df


def cortes_zqm(df: pd.DataFrame, edad=(8, 24), tch=(30, 250)) -> pd.DataFrame:
    """Un ciclo por suerte + soca: une los meses consecutivos (≤2) de una misma cosecha y toma
    la fila de mayor TC-Total (el acumulado). TCH = TC-Total / área."""
    d = df[df["Empresa"].str.startswith(("02", "03"))].copy()
    d["planta"] = np.where(d["Empresa"].str.startswith("03"), "riopaila", "castilla")
    d["t"] = d["AÑO"] * 12 + d["Mes"] - 1
    d = d.dropna(subset=["t", "Corte"])
    d = d[~d["Ubic Técnica"].isin(["", "None", "nan"])].sort_values(["Ubic Técnica", "Corte", "t"])
    gap = d.groupby(["Ubic Técnica", "Corte"])["t"].diff()
    d["ciclo"] = (gap.isna() | (gap > 2)).astype(int).groupby([d["Ubic Técnica"], d["Corte"]]).cumsum()
    idx = d.assign(_tc=d["TC-Total"].fillna(-1)).groupby(["Ubic Técnica", "Corte", "ciclo"])["_tc"].idxmax()
    c = d.loc[idx].copy()
    c["tch"] = c["TC-Total"] / c["Area"]
    c = c[c["Area"].gt(0) & c["tch"].between(*tch) & c["Edad"].between(*edad)]
    out = pd.DataFrame({
        "sec_ste": c["Ubic Técnica"].values,
        "planta": c["planta"].values,
        "anio": c["AÑO"].astype(int).values,
        "mes": c["Mes"].astype(int).values,
        "corte": c["Corte"].astype(int).values,
        "variedad": c["Variedad Principal"].values,
        "ha": c["Area"].values,
        "edad": c["Edad"].values,
        "tch": c["tch"].values,
        "tipo_cosecha": c["Tipo Cosecha"].values,
    })
    out["t_cos"] = out.anio * 12 + out.mes - 1
    out["t_cut"] = out.t_cos - out.edad.round().astype(int)
    cos = [date(a, m, 15) for a, m in zip(out.anio, out.mes)]
    out["harvest"] = [x.isoformat() for x in cos]
    out["cut"] = [(x - timedelta(days=float(e) * _DIAS)).isoformat() for x, e in zip(cos, out.edad)]
    out["key"] = (out.sec_ste + "|" + out.anio.astype(str) + "|" + out.mes.astype(str) + "|"
                  + out.corte.astype(str))
    return out.drop_duplicates("key").sort_values(["sec_ste", "t_cos"]).reset_index(drop=True)


def zonas_maestro(carpeta=MAESTROS) -> dict:
    """{sec_ste: zona agroecológica} del maestro (el ZQM 2023-26 la trae dañada)."""
    z = {}
    for fn in ("maestro_suertes.json", "maestro_castilla.json"):
        p = Path(carpeta) / fn
        if p.exists():
            for sec, v in json.load(open(p, encoding="utf-8")).items():
                z[sec] = v.get("zona_agroecologica")
    return z


# ---------------------------------------------------------------- historia propia (solo pasado)
def previa(valores: pd.Series, grupo: pd.Series) -> pd.Series:
    """Media de los ciclos ANTERIORES del mismo grupo, sin el actual (filas ordenadas en el tiempo)."""
    x = valores.fillna(0.0)
    n = valores.notna().astype(float)
    cs = x.groupby(grupo).cumsum() - x
    cn = n.groupby(grupo).cumsum() - n
    return (cs / cn).where(cn > 0)


def historia_tch(c: pd.DataFrame) -> pd.DataFrame:
    """TCH de los ciclos anteriores de la misma suerte. `c` ordenado por suerte y cosecha."""
    g = c.groupby("sec_ste")
    tchm = c["tch"] / c["edad"]
    return pd.DataFrame({
        "prev_tch1": g["tch"].shift(1),
        "prev_tch3": g["tch"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean()),
        "prev_tchm3": tchm.groupby(c["sec_ste"]).transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean()),
        "prev_n": g.cumcount(),
    }, index=c.index)


# variedades que no dicen cuál hay sembrada: no cuentan como cambio de variedad
VAR_SIN_DATO = {"", "VARIAS", "RENOVACION", "NAN", "NONE", "#N/A"}
ANALOGOS = ("ndmi_e5_8", "evi_e5_8", "ndvi_e5_8", "ndmi_e9_11", "evi_e9_11")


def plantios(c: pd.DataFrame, var_map: dict) -> pd.Series:
    """Clave del plantío de cada ciclo ("sec_ste#n"). Un plantío nuevo empieza cuando el número
    de corte baja respecto al ciclo anterior de la suerte (se renovó) o cambia la variedad.
    `c` ordenado por suerte y cosecha. Un corte desconocido (NaN) no cuenta como renovación."""
    var = c["variedad"].map(lambda v: (map_variedad(v, var_map) or str(v) or "").strip().upper())
    prev_c = c.groupby("sec_ste")["corte"].shift(1)
    prev_v = var.groupby(c["sec_ste"]).shift(1)
    cambio_var = prev_v.notna() & (var != prev_v) & ~var.isin(VAR_SIN_DATO) & ~prev_v.isin(VAR_SIN_DATO)
    nuevo = (c.groupby("sec_ste").cumcount() == 0) | (c["corte"] < prev_c) | cambio_var
    return c["sec_ste"] + "#" + nuevo.astype(int).groupby(c["sec_ste"]).cumsum().astype(str)


# ---------------------------------------------------------------- clima (ERA5-Land)
def cargar_clima(ruta=CLIMA, base=CLIMA_BASE) -> dict:
    """{(planta, sec_ste | None, t): anomalía de tmax (°C)} frente a la climatología del mes.

    Solo tmax: frente a las estaciones de Riopaila sus anomalías siguen bien (r=0,82), la lluvia y
    la humedad de ERA5 no (r≈0,3-0,4). La clave con sec_ste None es la media de la planta, de
    respaldo para suertes que no están en el geojson.
    """
    c = pd.read_csv(ruta)
    c["t"] = c.anio * 12 + c.mes - 1
    clim = c[c.anio.between(*base)].groupby(["planta", "sec_ste", "mes"]).tmax.mean().rename("clim")
    c = c.join(clim, on=["planta", "sec_ste", "mes"])
    c["a"] = c.tmax - c.clim
    out = {(p, s, t): a for p, s, t, a in zip(c.planta, c.sec_ste, c.t, c.a)}
    for (p, t), a in c.groupby(["planta", "t"]).a.mean().items():
        out[(p, None, t)] = a
    return out


def _tmax(clima: dict, planta: str, sec: str, t: int):
    v = clima.get((planta, sec, t))
    return clima.get((planta, None, t)) if v is None or v != v else v


def rasgos_clima(clima: dict, planta: str, sec: str, t_cut: int, t_obs: int) -> dict:
    """Calor de los ~60 días previos a la observación (mes de observación y el anterior) y calor
    medio del ciclo hasta la observación. Solo usa meses ya transcurridos."""
    fin = [_tmax(clima, planta, sec, t) for t in (t_obs - 1, t_obs)]
    ciclo = [_tmax(clima, planta, sec, t) for t in range(t_cut + 1, t_obs + 1)]
    fin = [v for v in fin if v is not None and v == v]
    ciclo = [v for v in ciclo if v is not None and v == v]
    return {"clima_tmax60": float(np.mean(fin)) if fin else np.nan,
            "clima_tmax_ciclo": float(np.mean(ciclo)) if ciclo else np.nan}


# ---------------------------------------------------------------- dosel mensual por edad
def cargar_mensual(plantas=("riopaila", "castilla"), ruta: str = MENSUAL) -> pd.DataFrame:
    partes = []
    for p in plantas:
        f = Path(ruta.format(planta=p))
        if f.exists():
            m = pd.read_csv(f)
            m["planta"] = p
            partes.append(m)
    m = pd.concat(partes, ignore_index=True).drop_duplicates(["planta", "sec_ste", "anio", "mes"])
    m["t"] = m.anio * 12 + m.mes - 1
    return m


def dosel_por_edad(c: pd.DataFrame, m: pd.DataFrame, max_edad: int = 15) -> pd.DataFrame:
    """Una fila por ciclo (i = posición en `c`) y mes de edad a = 0..edad (a=0 es el mes del corte)."""
    n = np.minimum(c["edad"].round().astype(int).values, max_edad)
    rep = np.repeat(np.arange(len(c)), n + 1)
    a = np.concatenate([np.arange(k + 1) for k in n]) if len(n) else np.array([], int)
    L = pd.DataFrame({"i": rep, "a": a, "planta": c["planta"].values[rep],
                      "sec_ste": c["sec_ste"].values[rep], "t": c["t_cut"].values[rep] + a})
    return L.merge(m[["planta", "sec_ste", "t", *INDICES_CURVA]], on=["planta", "sec_ste", "t"], how="left")


def medias_tramo(L: pd.DataFrame, n_ciclos: int, obs=None) -> pd.DataFrame:
    """Media de cada índice por tramo de edad, usando solo los meses ya observados (≤ obs)."""
    cols = {}
    for nom, (a0, a1) in TRAMOS.items():
        hasta = a1 if obs is None else min(a1, obs)
        if hasta < a0:
            continue
        g = L[(L.a >= a0) & (L.a <= hasta)].groupby("i")[list(INDICES_ANOM)].mean()
        for idx in INDICES_ANOM:
            cols[f"{idx.lower()}_{nom}"] = g[idx]
    return pd.DataFrame(cols).reindex(range(n_ciclos))


def _mes_iso(t: int) -> str:
    return f"{t // 12}-{t % 12 + 1:02d}-01"


# ---------------------------------------------------------------- ensamblado
META = ["_key", "_sec", "_planta", "_anio", "_mes", "_obs", "_tch", "_ha", "_tipo"]


def construir(c: pd.DataFrame, m: pd.DataFrame, sintetico, var_map: dict, zonas: dict,
              edades_obs=EDADES_OBS, desde: int = 2019, min_puntos: int = 3,
              clima: dict | None = None, solo: dict | None = None) -> pd.DataFrame:
    """Filas de entrenamiento (rasgos + columnas META con prefijo "_").

    `c` debe traer TODOS los ciclos (desde 2011) para que la historia de TCH esté completa;
    solo se generan filas para los cosechados desde `desde` (hay óptico desde dic-2018).
    Tipo de cosecha: `tipo_mec` es el de la cosecha que se predice (no siempre se sabe antes) y
    `prev_mec` el de la anterior (siempre se sabe).
    `solo` = {key: edad de observación (meses) o None}: arma solo esas filas, cada una a su edad
    (así se estiman los ciclos en curso, que van al final de `c` con tch vacío).
    """
    if solo is not None:
        edades_obs = sorted(set(solo.values()), key=lambda o: (o is None, o or 0))
    c = c.sort_values(["sec_ste", "t_cos"]).reset_index(drop=True)
    mec = c["tipo_cosecha"].map({"Mecanico": 1.0, "Manual": 0.0})
    tipo = pd.DataFrame({"tipo_mec": mec, "prev_mec": mec.groupby(c["sec_ste"]).shift(1)}).to_dict("records")
    H = historia_tch(c).to_dict("records")
    pl = plantios(c, var_map)
    Hp = historia_tch(c.assign(sec_ste=pl)).add_suffix("_p")
    prev_tch1_p = Hp["prev_tch1_p"]
    Hp = Hp.to_dict("records")
    L = dosel_por_edad(c, m)
    curvas = {}
    for i, g in L.groupby("i"):
        curvas[i] = {idx: [{"from": _mes_iso(t), "mean": float(v)} for t, v in zip(g.t, g[idx]) if pd.notna(v)]
                     for idx in INDICES_CURVA}
    filas = []
    for obs in edades_obs:
        T = medias_tramo(L, len(c), obs)
        A = pd.DataFrame({f"anom_{k}": T[k] - previa(T[k], c["sec_ste"]) for k in T.columns}, index=T.index)
        Ap = pd.DataFrame({f"anomp_{k}": T[k] - previa(T[k], pl) for k in T.columns}, index=T.index)
        # ciclo anterior del plantío visto a la misma edad de observación
        ant = pd.DataFrame({k: T[k].groupby(pl).shift(1) for k in T.columns}, index=T.index)
        Al = pd.DataFrame({f"anoml_{k}": T[k] - ant[k] for k in T.columns}, index=T.index)
        for t in TRAMOS:
            if f"anom_ndmi_{t}" in A:  # agua del dosel relativa a su verdor: la firma de 2023 y 2026
                A[f"anom_dif_{t}"] = A[f"anom_ndmi_{t}"] - A[f"anom_ndvi_{t}"]
                Ap[f"anomp_dif_{t}"] = Ap[f"anomp_ndmi_{t}"] - Ap[f"anomp_ndvi_{t}"]
        An = pd.DataFrame({f"analog_{k}": prev_tch1_p * (T[k] / ant[k]).where(ant[k].abs() > 0.05).clip(0.5, 1.5)
                           for k in ANALOGOS if k in T}, index=T.index)
        # con caña joven puede no haber ningún tramo comparable: to_dict de un DataFrame sin columnas da []
        A, Ap, Al, An = (x.to_dict("records") if x.shape[1] else [{}] * len(c) for x in (A, Ap, Al, An))
        for i, r in enumerate(c.itertuples(index=False)):
            if solo is not None:
                if r.key not in solo or solo[r.key] != obs:
                    continue
            elif r.anio < desde:
                continue
            if obs is not None and obs >= r.edad - 0.5:
                continue  # la caña se cortó antes de esa edad: la fila completa ya la representa
            reg = {"variedad": r.variedad, "corte": r.corte, "edad": r.edad, "mes": r.mes, "ha": r.ha,
                   "zona_agro": zonas.get(r.sec_ste), "cut": r.cut, "curves": curvas.get(i, {})}
            f = build_features(reg, sintetico, var_map, max_age=obs, indices=INDICES_CURVA)
            if f["ndvi_n"] < min_puntos:
                continue
            f.pop("aforo_vivo", None)
            f["edad_obs"] = float(r.edad if obs is None else obs)
            f["castilla"] = int(r.planta == "castilla")
            for x in (H[i], Hp[i], A[i], Ap[i], Al[i], An[i], tipo[i]):
                f.update(x)
            if clima is not None:
                t_obs = r.t_cos if obs is None else r.t_cut + obs
                f.update(rasgos_clima(clima, r.planta, r.sec_ste, r.t_cut, t_obs))
            f.update(_key=r.key, _sec=r.sec_ste, _planta=r.planta, _anio=r.anio, _mes=r.mes,
                     _obs="completo" if obs is None else f"{obs} meses", _tch=r.tch, _ha=r.ha,
                     _tipo=r.tipo_cosecha)
            filas.append(f)
    return pd.DataFrame(filas)


def rasgos(df: pd.DataFrame, quitar=()) -> pd.DataFrame:
    """Solo las columnas del modelo (sin META), opcionalmente sin los grupos `quitar`:
    "historia" (prev_*, anomalías y análogos), "satelite" (curvas, anomalías y análogos),
    "clima" (clima_*), "tipo" (tipo_mec y prev_mec), "tipo_actual" (solo tipo_mec),
    "plantio" (historia y comparaciones dentro del plantío: el motor de antes del 16-oct-2026)."""
    cols = [c for c in df.columns if not c.startswith("_")]
    sat = tuple(i.lower() + "_" for i in INDICES_CURVA)
    anom = ("anom_", "anomp_", "anoml_", "analog_")
    if "plantio" in quitar:
        cols = [c for c in cols if not (c.endswith("_p") and c.startswith("prev_"))
                and not c.startswith(("anomp_", "anoml_", "analog_"))]
    if "clima" in quitar:
        cols = [c for c in cols if not c.startswith("clima_")]
    if "tipo" in quitar:
        cols = [c for c in cols if c not in ("tipo_mec", "prev_mec")]
    if "tipo_actual" in quitar:
        cols = [c for c in cols if c != "tipo_mec"]
    if "historia" in quitar:
        cols = [c for c in cols if not c.startswith(("prev_",) + anom)]
    if "satelite" in quitar:
        cols = [c for c in cols if not c.startswith(sat + anom) and c != "edad_obs"]
    return df[cols]
