"""Servicio de estimación TCH al vuelo (Opción B — Render).

Entrena el motor una vez al arrancar (reusa JobEstimados) y expone un endpoint
que estima UNA suerte por request: resuelve su agronomía en el maestro, extrae la
curva satelital (endpoint público de Rio Map), predice y recalibra.

Env:
  TCH_SUPABASE_URL   (obligatorio)  URL del Supabase de Rio Map
  TCH_SUPABASE_ANON  (obligatorio)  anon key — lee var_map/aforo_sintetico/factor
  TCH_SUPABASE_KEY   (opcional)     service_role — solo si se pide guardar el estimado
  ALLOW_ORIGIN       (opcional)     origen del tablero para CORS (def: *)

Endpoints:
  GET /health
  GET /estimar?sec=2503-200[&fecha=2026-09-30][&guardar=1]
"""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# el paquete tchmotor vive en la raíz del repo (padre de service/)
_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_DIR.parent))

from flask import Flask, jsonify, request
from flask_cors import CORS

from tchmotor import Supabase, JobEstimados, curva_suerte

_DATA = _DIR / "data"
_DIAS_MES = 30.44
FIJOS = {"riopaila": 0.981, "castilla": 0.914}

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": os.environ.get("ALLOW_ORIGIN", "*")}})


class Estado:
    def __init__(self):
        url = os.environ["TCH_SUPABASE_URL"]
        anon = os.environ["TCH_SUPABASE_ANON"]
        self.sb_read = Supabase(url=url, key=anon)          # lecturas (anon, RLS)
        self.job = JobEstimados(self.sb_read, curva_suerte).entrenar()
        self.factores = dict(FIJOS)
        try:
            self.factores.update(self.sb_read.cargar_factores())
        except Exception:
            pass
        self.maestro = {}
        for fn in ("maestro_suertes.json", "maestro_castilla.json"):
            self.maestro.update(json.load(open(_DATA / fn, encoding="utf-8")))
        self.idx = json.load(open(_DATA / "tablones_index.json", encoding="utf-8"))
        # cliente de escritura opcional (service_role)
        skey = os.environ.get("TCH_SUPABASE_KEY")
        self.sb_write = Supabase(url=url, key=skey) if skey else None

    def suerte(self, sec, harvest_iso):
        v = self.maestro.get(sec)
        if not v:
            return None, "sec-ste no está en el maestro"
        if (v.get("uso") or "").strip().upper() not in ("CAÑA", "CANA"):
            return None, "la suerte no está en caña"
        var = v.get("variedad")
        if var in (None, "RENOVACION", "VARIAS"):
            return None, "variedad no estimable (%s)" % var
        if sec not in self.idx:
            return None, "sin tablón mapeado (no hay curva satelital)"
        tab_id, _ha, planta = self.idx[sec]
        edad = v.get("edad_csv")
        if edad is None:
            return None, "sin edad en el maestro"
        harvest = date.fromisoformat(harvest_iso)
        cut = (harvest - timedelta(days=float(edad) * _DIAS_MES)).isoformat()
        return {
            "sec_ste": sec, "planta": planta, "tab_id": tab_id,
            "cut": cut, "harvest": harvest_iso,
            "edad": round(float(edad), 1), "corte": v.get("numero_corte"),
            "variedad": var, "zona_agro": v.get("zona_agroecologica"),
            "ha": v.get("area_neta_ha"), "area": v.get("area_neta_ha"),
            "fecha_corte_prevista": _iso(v.get("fecha_proximo_corte")),
        }, None


def _iso(s):
    try:
        date.fromisoformat(str(s)[:10])
        return str(s)[:10]
    except Exception:
        return None


ESTADO = None  # se inicializa perezoso (primer request) para no fallar el import


def estado():
    global ESTADO
    if ESTADO is None:
        ESTADO = Estado()
    return ESTADO


@app.get("/health")
def health():
    # liviano: no entrena (el primer /estimar hace la carga en frío)
    return jsonify(ok=True, listo=ESTADO is not None)


@app.get("/")
def raiz():
    return jsonify(servicio="estimador-tch-api", uso="GET /estimar?sec=SEC-STE")


@app.get("/estimar")
def estimar():
    sec = (request.args.get("sec") or "").strip()
    if not sec:
        return jsonify(error="falta ?sec="), 400
    harvest = request.args.get("fecha") or date.today().isoformat()
    if _iso(harvest) is None:
        return jsonify(error="fecha inválida (usa AAAA-MM-DD)"), 400
    e = estado()
    s, err = e.suerte(sec, harvest)
    if err:
        return jsonify(sec_ste=sec, estimable=False, motivo=err), 200
    filas = e.job.estimar([s], harvest, factores=e.factores)
    if not filas:
        return jsonify(sec_ste=sec, estimable=False,
                       motivo="sin dato satelital en la ventana (nube)"), 200
    f = filas[0]
    f["estimable"] = True
    f["fecha_corrida"] = harvest
    if request.args.get("guardar") == "1" and e.sb_write:
        try:
            e.sb_write.guardar_estimados([{k: f[k] for k in (
                "sec_ste", "planta", "fecha_corrida", "fecha_corte_prevista", "edad_meses",
                "soca", "variedad", "tch_estimado", "tch_std", "ton_estimadas", "area_ha",
                "modo", "factor_recal", "modelo_version")}])
            f["guardado"] = True
        except Exception as ex:
            f["guardado"] = False
            f["guardar_error"] = str(ex)[:120]
    return jsonify(f)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
