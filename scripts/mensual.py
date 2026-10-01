# -*- coding: utf-8 -*-
"""Corrida mensual del estimador de TCH, sin base de datos.

1. Earth Engine: agrega a la tabla mensual el mes vigente y rehace el anterior (quedó incompleto).
2. ZQM (Excel) → ciclos cosechados; base de aforos (Excel) → aforo sintético; maestro oficial
   (maestro.csv de maestro-riopaila) → suertes en curso y su edad.
3. Entrena con las campañas completas anteriores y calcula el factor de la campaña con sus cosechas
   ya cerradas.
4. Estima todas las suertes en curso y escribe los JSON del tablero: estimados, reales, factores,
   curvas por suerte y meta (más una copia de los estimados en historial/).

Uso:
  .venv-gee\\Scripts\\python.exe scripts\\mensual.py                 # corrida completa
  .venv-gee\\Scripts\\python.exe scripts\\mensual.py --sin-gee       # sin actualizar el satélite
  opciones: --fecha AAAA-MM-DD  --salida <carpeta data del tablero>  --arboles 600
"""
import argparse
import os
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd  # noqa: E402

from tchmotor import AforoSintetico, cargar_var_map  # noqa: E402
from tchmotor import dataset_gee as dg  # noqa: E402
from tchmotor import produccion as pr  # noqa: E402
from tchmotor.aforo import registros_aforo_excel  # noqa: E402

AFOROS = os.path.join(os.path.expanduser("~"), "Documents", "Base de aforos completa 2026.xlsx")
SALIDA = os.path.join(os.path.expanduser("~"), "tch-dashboard", "data")


def log(s):
    print(s, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", default=None, help="fecha de la corrida (def: hoy)")
    ap.add_argument("--salida", default=SALIDA)
    ap.add_argument("--sin-gee", action="store_true", help="no actualiza la tabla mensual de Earth Engine")
    ap.add_argument("--arboles", type=int, default=600)
    a = ap.parse_args()
    hoy = date.fromisoformat(a.fecha) if a.fecha else date.today()
    t_now = pr.mes_vigente(hoy)
    mes_txt = lambda t: f"{t // 12}-{t % 12 + 1:02d}"  # noqa: E731
    campana = hoy.year
    t0 = time.time()
    log(f"Corrida {hoy} · campaña {campana} · satélite hasta {mes_txt(t_now)}")

    if not a.sin_gee:
        from tchmotor import gee

        gee.iniciar()
        for planta in ("riopaila", "castilla"):
            gee.actualizar_tabla_mensual(planta, mes_txt(t_now - 1), mes_txt(t_now), rehacer_desde=mes_txt(t_now - 1),
                                         log=log)

    c = dg.cortes_zqm(dg.leer_zqm())
    zqm_hasta = f"{c.anio.max()}-{c[c.anio == c.anio.max()].mes.max():02d}"
    maestro, fuente_maestro = pr.cargar_maestro()
    log(f"Maestro: {len(maestro)} suertes · {fuente_maestro}")
    rec, fuera_rec = pr.cosechas_recientes(pr.leer_cosechas_recientes(), maestro, c)
    c = pd.concat([c, rec], ignore_index=True).drop_duplicates("key").sort_values(["sec_ste", "t_cos"])
    c = c.reset_index(drop=True)
    log(f"Cosechas recientes (complemento del ZQM): {len(rec)} agregadas · fuera: {dict(fuera_rec)}")
    m = dg.cargar_mensual()
    ultimo_sat = int(m.t.max())
    sint = AforoSintetico(registros_aforo_excel(AFOROS), min_n=4)
    # zona agroecológica del maestro oficial; las suertes que ya salieron de él la conservan de Rio Map
    vm = cargar_var_map()
    zonas = {**dg.zonas_maestro(), **{s: v["zona_agroecologica"] for s, v in maestro.items() if v["zona_agroecologica"]}}
    log(f"Cosechas: {len(c)} (ZQM hasta {zqm_hasta}, última {c.harvest.max()}) · "
        f"satélite hasta {mes_txt(ultimo_sat)} · {time.time() - t0:.0f} s")

    hist = dg.construir(c, m, sint, vm, zonas)
    motor = pr.entrenar(hist, campana, a.arboles)
    factores, cerr = pr.factor_campana(motor, hist, campana)
    for p, f in factores.items():
        log(f"  factor {p}: {f['factor']} ({f['cosechas']} cosechas cerradas, modelo {f['sesgo_modelo_pct']:+.1f}%, "
            f"MAPE {f['mape_modelo_pct']}%){'' if f['aplica'] else ' · aún no aplica'}")

    activos, fuera = pr.ciclos_activos(maestro, c, min(t_now, ultimo_sat), hoy)
    todos = pd.concat([c, activos[dg.COLS_CICLO]], ignore_index=True)
    solo = {k: (None if v is None or v != v else int(v)) for k, v in zip(activos["key"], activos["_obs"])}
    filas = dg.construir(todos, m, sint, vm, zonas, solo=solo)
    sin_sat = len(activos) - len(filas)
    estimados = pr.estimar(motor, filas, activos, factores, hoy.isoformat())
    log(f"Estimadas {len(estimados)} suertes en curso · fuera: {dict(fuera)} · sin satélite suficiente: {sin_sat}")

    curvas = pr.curvas(todos, m, estimados)
    meta = {
        "fecha_corrida": hoy.isoformat(), "campana": campana, "modelo_version": pr.VERSION,
        "satelite_hasta": mes_txt(ultimo_sat), "zqm_hasta": zqm_hasta, "cosechas_hasta": c.harvest.max(),
        "cosechas_recientes": int(len(rec)),
        "entrenado_con": f"cosechas 2019-{campana - 1}",
        "ciclos_entrenamiento": int(hist[hist._anio < campana]._key.nunique()),
        "fuentes": ["Earth Engine (Sentinel-2)", "ZQM histórico y 2026 (Excel)", "Base de aforos (Excel)",
                    "Maestro de suertes (maestro-riopaila)"],
        "suertes_estimadas": len(estimados), "descartadas": {**dict(fuera), "sin satélite suficiente": sin_sat},
    }
    pr.escribir(a.salida, estimados, pr.reales(cerr, campana), factores, curvas, meta)
    ton = sum(e["ton_estimadas"] or 0 for e in estimados)
    log(f"Escrito en {a.salida}: {len(estimados)} estimados ({ton:,.0f} t), {len(cerr)} reales, "
        f"{len(curvas)} curvas · {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
