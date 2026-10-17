# -*- coding: utf-8 -*-
"""Pone el estimado del motor en los aforos de la app de Turnos (barra «Modelo» de Evaluaciones → Aforo).

Cada aforo guarda el estimado que vio el técnico al capturarlo (`tch_modelo`, `modelo_corrida`...). Tras una
corrida nueva del motor, este programa lo actualiza solo donde la comparación sigue siendo del mismo ciclo:

  * Suerte EN PIE con la misma soca que el aforo → el estimado de la corrida vigente (estimados.json).
  * Aforo SIN estimado guardado → el de la corrida que estaba vigente el día del aforo (historial/), si la hay
    con la misma soca.
  * Suerte ya cosechada con estimado guardado → no se toca: la corrida nueva ya no estima ese ciclo, y lo
    guardado es el estimado de antes del corte, que es la comparación justa.

`desv_modelo` = TCH por pesos − TCH del modelo (como la app). Sin `--aplicar` solo muestra lo que cambiaría;
con `--aplicar` guarda antes un respaldo de los valores anteriores en 01 Estimados y TCH.

Uso:  .venv-gee\\Scripts\\python.exe scripts\\modelo_en_aforos.py [--aplicar]
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tchmotor import rutas, turnos  # noqa: E402

PLANTA = "riopaila"  # la app de Turnos es de Riopaila
CAMPOS = ("tch_modelo", "tch_modelo_std", "modelo_corrida", "modelo_fecha_corte", "desv_modelo")


def _cargar(ruta):
    return {e["sec_ste"]: e for e in json.load(open(ruta, encoding="utf-8")) if e["planta"] == PLANTA}


def _misma_soca(aforo, est):
    return aforo["numero_corte"] is None or est.get("soca") is None or int(aforo["numero_corte"]) == int(est["soca"])


def _igual(x, y):
    if isinstance(y, float) and x is not None:
        return abs(float(x) - y) < 1e-3
    return x == y


def _valores(aforo, est, corrida):
    tch = float(est["tch_estimado"])
    pesos = aforo["tch_pesos"]
    return {"tch_modelo": tch, "tch_modelo_std": est.get("tch_std"), "modelo_corrida": corrida,
            "modelo_fecha_corte": (est.get("fecha_corte_prevista") or "")[:10] or None,
            "desv_modelo": None if pesos is None else float(pesos) - tch}


def plan(aforos, vigente, fecha_vigente, historial):
    """[(aforo, valores nuevos, motivo)] solo para los que cambian."""
    out = []
    for a in aforos:
        s = str(a["suerte"] or "").strip().upper()
        e = vigente.get(s)
        if e is not None and _misma_soca(a, e):
            nuevo, motivo = _valores(a, e, fecha_vigente), "en pie"
        elif a["tch_modelo"] is None:
            previas = [(d, h[s]) for d, h in historial.items() if d <= a["date"] and s in h and _misma_soca(a, h[s])]
            if not previas:
                continue
            d, e = previas[-1]
            nuevo, motivo = _valores(a, e, d), f"vigente el {d}"
        else:
            continue
        if any(not _igual(a.get(k), v) for k, v in nuevo.items()):
            out.append((a, nuevo, motivo))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="escribe en la base de la app de Turnos")
    a = ap.parse_args()
    meta = json.load(open(rutas.TABLERO_DATA / "meta.json", encoding="utf-8"))
    vigente = _cargar(rutas.TABLERO_DATA / "estimados.json")
    historial = {p.stem.split("_", 1)[1]: _cargar(p)
                 for p in sorted((rutas.TABLERO_DATA / "historial").glob("estimados_*.json"))}
    filas = turnos.aforos()
    cambios = plan(filas, vigente, meta["fecha_corrida"], historial)
    print(f"{len(filas)} aforos · corrida vigente {meta['fecha_corrida']} ({meta['modelo_version']}) · "
          f"{len(cambios)} por actualizar")
    for x, n, motivo in sorted(cambios, key=lambda c: (c[0]["date"], c[0]["suerte"])):
        antes = "sin estimado" if x["tch_modelo"] is None else f"{float(x['tch_modelo']):.1f} ({x['modelo_corrida']})"
        print(f"  {x['date']} {x['suerte']} corte {x['numero_corte']}: {antes} → {n['tch_modelo']:.1f} "
              f"({n['modelo_corrida']}) · {motivo}")
    if not a.aplicar or not cambios:
        print("nada escrito" + (" (simulación: usa --aplicar)" if cambios else ""))
        return
    resp = rutas.ESTIMADOS_DIR / f"respaldo_modelo_en_aforos_{date.today().isoformat()}.json"
    previos = json.loads(resp.read_text(encoding="utf-8")) if resp.exists() else []
    ya = {p["id"] for p in previos}
    previos += [{"id": x["id"], "suerte": x["suerte"], "date": x["date"], **{k: x[k] for k in CAMPOS}}
                for x, _, _ in cambios if x["id"] not in ya]
    resp.write_text(json.dumps(previos, ensure_ascii=False, indent=1), encoding="utf-8")
    print("respaldo:", resp)
    url, key = turnos._credenciales()
    for x, n, _ in cambios:
        req = urllib.request.Request(f"{url}/rest/v1/aforo_records?id=eq.{x['id']}", method="PATCH",
                                     data=json.dumps(n).encode("utf-8"),
                                     headers={"apikey": key, "Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json", "Prefer": "return=representation"})
        with urllib.request.urlopen(req, timeout=60) as r:
            if len(json.loads(r.read().decode("utf-8"))) != 1:
                raise RuntimeError(f"el aforo {x['id']} no se actualizó (¿RLS o id inexistente?)")
    print(f"actualizados {len(cambios)} aforos")


if __name__ == "__main__":
    main()
