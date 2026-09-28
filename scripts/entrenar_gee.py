# -*- coding: utf-8 -*-
"""Reentrena el estimador de TCH con Earth Engine y lo compara con el modelo actual.

1. Arma el dataset: ciclos del ZQM (2011-2026, para la historia) × tabla mensual de Earth
   Engine (data/gee/mensual_<planta>.csv) × edades de observación 6/8/10 meses y ciclo completo.
2. Valida fuera de muestra por año de cosecha (entrena con los años anteriores):
     2025 ← 2019-2024 · 2026 ← 2019-2025 · 2026 ← 2019-2024 (mismo entrenamiento que el actual)
   con variantes que suman calor de fin de ciclo (ERA5-Land) y tipo de cosecha (el de la anterior,
   que se sabe antes del corte, o el real), una sin satélite y la persistencia (media de los
   últimos 3 cortes de la suerte).
3. Compara contra el modelo actual (504 ciclos, Copernicus) en las mismas suertes:
   Documents/Estimados_2025.csv y Documents/Cosechado_2026_estimado.csv.

No toca producción. Uso:
  .venv-gee\\Scripts\\python.exe scripts\\entrenar_gee.py [--rehacer] [--arboles 300]
Salidas en data/gee/: dataset_gee.pkl, validacion_predicciones.csv, validacion_gee.txt
"""
import argparse
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from tchmotor import AforoSintetico, AforoSinteticoTabla, MotorTCH, Supabase, cargar_var_map  # noqa: E402
from tchmotor import dataset_gee as dg  # noqa: E402

RAIZ = dg._RAIZ
OUT = RAIZ / "data" / "gee"
DOCS = os.path.join(os.path.expanduser("~"), "Documents")
ACTUAL = {2025: os.path.join(DOCS, "Estimados_2025.csv"), 2026: os.path.join(DOCS, "Cosechado_2026_estimado.csv")}
RIOMAP_ENV = r"C:\Users\Agr349\agrocontrol-campo\.env.local"
ESCENARIOS = [("2025", 2024, 2025), ("2026", 2025, 2026), ("2026 · entrenado hasta 2024", 2024, 2026)]
# "nuevo" = satélite + historia propia + agronomía. El calor de fin de ciclo (ERA5-Land) y el tipo
# de cosecha (el de la anterior, que se sabe antes del corte, o el real) se prueban encima: no
# mejoran fuera de muestra (27-sep-2026), por eso quedan fuera del principal.
VARIANTES = {
    "nuevo": ("clima", "tipo"),
    "+ calor": ("tipo",),
    "+ calor + tipo anterior": ("tipo_actual",),
    "+ calor + tipo real": (),
    "sin satélite": ("satelite", "clima", "tipo"),
}
PRINCIPAL = "nuevo"
RECAL_MIN = 15  # cosechas ya cerradas en la campaña para recalibrar
OBS = ["6 meses", "8 meses", "10 meses", "completo"]


def _env(path, name):
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def aforo_sintetico():
    """Tabla tch_aforo_sintetico de Rio Map; si Supabase no responde (p. ej. 402), el mismo
    cálculo desde la base de aforos local que usa scripts/seed_referencia.py."""
    try:
        sb = Supabase(url=_env(RIOMAP_ENV, "NEXT_PUBLIC_SUPABASE_URL"),
                      key=_env(RIOMAP_ENV, "NEXT_PUBLIC_SUPABASE_ANON_KEY"))
        return AforoSinteticoTabla(sb.cargar_aforo_sintetico())
    except Exception as e:
        print(f"aviso: Supabase de Rio Map no responde ({str(e)[:60]}); aforo sintético desde la base local",
              flush=True)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from seed_referencia import registros_aforo

        return AforoSintetico(registros_aforo(), min_n=4)


def dataset(rehacer: bool) -> pd.DataFrame:
    destino = OUT / "dataset_gee.pkl"
    if destino.exists() and not rehacer:
        return pd.read_pickle(destino)
    t0 = time.time()
    sint = aforo_sintetico()
    c = dg.cortes_zqm(dg.leer_zqm())
    print(f"ciclos del ZQM: {len(c)} ({c.anio.min()}-{c.anio.max()}) · {time.time() - t0:.0f} s", flush=True)
    d = dg.construir(c, dg.cargar_mensual(), sint, cargar_var_map(), dg.zonas_maestro(),
                     clima=dg.cargar_clima())
    d.to_pickle(destino)
    print(f"dataset: {len(d)} filas · {d._key.nunique()} ciclos · {time.time() - t0:.0f} s", flush=True)
    return d


def metricas(d: pd.DataFrame, col: str) -> pd.Series:
    e = d[col] - d._tch
    ape = e.abs() / d._tch
    return pd.Series({"ciclos": len(d), "MAPE %": 100 * ape.mean(), "MAE t/ha": e.abs().mean(),
                      "sesgo %": 100 * ((d[col] * d._ha).sum() / (d._tch * d._ha).sum() - 1),
                      "±20 %": 100 * (ape <= 0.2).mean()})


def tabla(d, col, por):
    t = d.groupby(por).apply(lambda g: metricas(g, col))
    return t.round({"ciclos": 0, "MAPE %": 1, "MAE t/ha": 1, "sesgo %": 1, "±20 %": 0})


def validar(d: pd.DataFrame, arboles: int):
    preds, importancias = [], None
    for nombre, hasta, prueba in ESCENARIOS:
        tr = d[d._anio.between(2019, hasta)]
        base = d[d._anio == prueba]  # los rasgos salen de aquí, sin columnas agregadas
        te = base.copy()
        te["escenario"] = nombre
        for var, quitar in VARIANTES.items():
            t0 = time.time()
            m = MotorTCH(n_estimators=arboles).entrenar(dg.rasgos(tr, quitar), tr._tch.values)
            te[var] = m.predecir(dg.rasgos(base, quitar))
            print(f"  {nombre} · {var}: {len(tr)} filas de entrenamiento · {time.time() - t0:.0f} s", flush=True)
            if nombre == "2026" and var == PRINCIPAL:
                importancias = pd.Series(m.rf_.feature_importances_, index=m.cols_).sort_values(ascending=False)
        te["persistencia"] = te.prev_tch3.fillna(te.aforo_sint)
        preds.append(te)
    return pd.concat(preds, ignore_index=True), importancias


def recalibrar_en_campana(d: pd.DataFrame, col: str) -> pd.Series:
    """Factor por planta = Σreal·ha / Σpred·ha de las cosechas del MISMO año cerradas antes del mes
    que se estima (lo que hace la auto-recalibración si corre cada mes)."""
    k = pd.Series(1.0, index=d.index)
    for _, g in d.groupby("_planta"):
        for m in sorted(g._mes.unique()):
            ant = g[g._mes < m]
            if len(ant) >= RECAL_MIN:
                k[g.index[g._mes == m]] = (ant._tch * ant._ha).sum() / (ant[col] * ant._ha).sum()
    return d[col] * k


def contra_actual(p: pd.DataFrame):
    """Mismas suertes y mismo ciclo que evaluó el modelo actual (real ZQM a ±2 t/ha)."""
    filas = []
    for anio, ruta in ACTUAL.items():
        if not os.path.exists(ruta):
            continue
        a = pd.read_csv(ruta, encoding="utf-8-sig")[["sec_ste", "tch_estimado", "tch_real"]]
        for esc in [e for e, _, pr in ESCENARIOS if pr == anio]:
            q = p[(p.escenario == esc) & (p._obs == "completo")].merge(a, left_on="_sec", right_on="sec_ste")
            q = q[(q._tch - q.tch_real).abs() <= 2]
            q = q.loc[q.groupby("_sec").apply(lambda g: (g._tch - g.tch_real).abs().idxmin(), include_groups=False)]
            for planta, g in list(q.groupby("_planta")) + [("ambas", q)]:
                filas.append({"escenario": esc, "planta": planta, "modelo": "actual (Copernicus, 504 ciclos)",
                              **metricas(g, "tch_estimado")})
                filas.append({"escenario": esc, "planta": planta, "modelo": "nuevo (Earth Engine)",
                              **metricas(g, PRINCIPAL)})
    return pd.DataFrame(filas).round(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehacer", action="store_true", help="vuelve a armar el dataset")
    ap.add_argument("--arboles", type=int, default=300)
    a = ap.parse_args()
    d = dataset(a.rehacer)
    print("\nvalidando fuera de muestra…", flush=True)
    p, imp = validar(d, a.arboles)
    p.to_csv(OUT / "validacion_predicciones.csv", index=False)

    buf = io.StringIO()
    w = lambda s="": print(s, file=buf)  # noqa: E731
    pd.set_option("display.width", 200)
    w("ESTIMADOR TCH · REENTRENAMIENTO CON EARTH ENGINE")
    w(f"Dataset: {len(d)} filas · {d._key.nunique()} ciclos cosechados 2019-2026 · "
      f"{d._sec.nunique()} suertes · {d.shape[1] - len(dg.META)} rasgos")
    w(d[d._obs == "completo"].groupby(["_anio", "_planta"]).size().unstack().to_string())

    w("\n1) Contra el modelo actual, mismas suertes y mismo ciclo (curva completa, sin factor de recalibración)")
    w(contra_actual(p).to_string(index=False))

    comp = p[p._obs == "completo"]
    for esc, _, _ in ESCENARIOS:
        w(f"\n2) Escenario {esc} · curva completa · por variante y planta")
        e = comp[comp.escenario == esc]
        partes = []
        for var in list(VARIANTES) + ["persistencia"]:
            t = tabla(e, var, "_planta")
            t.insert(0, "variante", var)
            partes.append(t.reset_index())
        w(pd.concat(partes).to_string(index=False))

    w(f"\n3) Caña joven · modelo {PRINCIPAL} por edad de observación (escenario 2026)")
    e = p[p.escenario == "2026"]
    t = e.groupby(["_planta", "_obs"]).apply(lambda g: metricas(g, PRINCIPAL)).round(1)
    w(t.reindex(OBS, level=1).to_string())

    w("\n4) 2026 por planta, tipo de cosecha y mes (curva completa): sesgo % por variante")
    e = comp[comp.escenario == "2026"]
    for por in (["_planta", "_tipo"], ["_planta", "_mes"]):
        t = e.groupby(por).apply(lambda g: pd.Series(
            {"ciclos": len(g), **{v: metricas(g, v)["sesgo %"] for v in list(VARIANTES)[:4]}}))
        w(t.round(1).to_string())

    w(f"\n4b) Recalibración dentro de la campaña (factor por planta con las cosechas ya cerradas del año,"
      f" mínimo {RECAL_MIN}) · modelo {PRINCIPAL} · curva completa")
    partes = []
    for esc in ("2025", "2026"):
        e = comp[comp.escenario == esc].copy()
        e["recalibrado"] = recalibrar_en_campana(e, PRINCIPAL)
        for col, nom in ((PRINCIPAL, "sin recalibrar"), ("recalibrado", "recalibrado")):
            t = tabla(e, col, "_planta").reset_index()
            t.insert(0, "variante", nom)
            t.insert(0, "escenario", esc)
            partes.append(t)
    w(pd.concat(partes).to_string(index=False))

    w(f"\n5) Rasgos que más pesan (modelo {PRINCIPAL} entrenado 2019-2025)")
    w(imp.head(20).round(3).to_string())
    texto = buf.getvalue()
    (OUT / "validacion_gee.txt").write_text(texto, encoding="utf-8")
    print("\n" + texto)


if __name__ == "__main__":
    main()
