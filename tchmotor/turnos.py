"""Cosechas terminadas del módulo de Cosecha de la app de Turnos (Riopaila), con el TCH de la app.

Replica `resumenCorte` de turnos-jornales/lib/cosecha/calculos.ts:
  área efectiva = área del maestro − área descontada (si queda en 0 o menos, no hay área)
  toneladas     = vagones (báscula si hay, si no el estimado) + caña de meses anteriores + caña sin vagones
  TCH           = toneladas ÷ área efectiva
El mes de una suerte es el de su fecha de cierre (`fecha_fin`).

Credenciales: NEXT_PUBLIC_SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY del .env.local de la app de Turnos
(ruta en `rutas.TURNOS_ENV`), o TCH_TURNOS_URL y TCH_TURNOS_KEY en el entorno (la app empaquetada).
Nunca se imprimen. Solo lectura.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from . import rutas

_COLS_CORTE = ("id,suerte,hacienda,zona,area_ha,area_descontada_ha,numero_corte,fecha_inicio,fecha_fin,tch_ppto,"
               "tch_anterior,edad_meses,estado,variedad,tipo_cosecha,ton_mes_anterior,ton_sin_vagones")


def _credenciales():
    url, key = os.environ.get("TCH_TURNOS_URL"), os.environ.get("TCH_TURNOS_KEY")  # la app empaquetada
    if url and key:
        return url.rstrip("/"), key
    if not rutas.TURNOS_ENV.exists():
        raise FileNotFoundError(f"No encuentro el .env.local de Turnos en {rutas.TURNOS_ENV} (ajusta TCH_TURNOS_ENV)")
    v = {}
    for linea in rutas.TURNOS_ENV.read_text(encoding="utf-8").splitlines():
        if "=" in linea:
            k, _, val = linea.partition("=")
            v[k.strip()] = val.strip().strip('"').strip("'")
    url, key = v.get("NEXT_PUBLIC_SUPABASE_URL"), v.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("El .env.local de Turnos no trae NEXT_PUBLIC_SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY")
    return url.rstrip("/"), key


def _get(url, key, tabla, params, desde, hasta):
    q = urllib.parse.urlencode(params, safe=",.:()*")
    req = urllib.request.Request(f"{url}/rest/v1/{tabla}?{q}", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items", "Range": f"{desde}-{hasta}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _todo(url, key, tabla, params, pagina=1000):
    """Todas las filas, paginando SIEMPRE con orden estable por id (sin `order` PostgREST repite y salta filas)."""
    out, i = [], 0
    while True:
        lote = _get(url, key, tabla, {**params, "order": "id"}, i, i + pagina - 1)
        out += lote
        if len(lote) < pagina:
            return out
        i += pagina


def cortes_terminados(desde: str, hasta: str) -> list[dict]:
    """Cortes con estado T y fecha de cierre entre `desde` y `hasta` (AAAA-MM-DD), con su TCH de la app."""
    url, key = _credenciales()
    cortes = _todo(url, key, "cosecha_cortes", {"select": _COLS_CORTE, "estado": "eq.T",
                                                 "and": f"(fecha_fin.gte.{desde},fecha_fin.lte.{hasta})"})
    out = []
    for c in cortes:
        vag = _todo(url, key, "cosecha_vagones", {"select": "id,peso_real_kg,peso_estimado_kg,fecha",
                                                  "corte_id": f"eq.{c['id']}"})
        kg = sum(float(v["peso_real_kg"]) if v["peso_real_kg"] is not None else float(v["peso_estimado_kg"] or 0)
                 for v in vag)
        ton = kg / 1000 + float(c["ton_mes_anterior"] or 0) + float(c["ton_sin_vagones"] or 0)
        area = None
        if c["area_ha"] is not None:
            area = round(float(c["area_ha"]) - float(c["area_descontada_ha"] or 0), 2)
            area = area if area > 0 else None
        fechas = sorted(v["fecha"] for v in vag if v["fecha"])
        out.append({
            "sec_ste": c["suerte"], "hacienda": c["hacienda"], "zona": c["zona"], "variedad": c["variedad"],
            "tipo_cosecha": c["tipo_cosecha"], "corte": c["numero_corte"], "fecha_inicio": c["fecha_inicio"],
            "fecha_fin": c["fecha_fin"], "primer_vagon": fechas[0] if fechas else None,
            "ultimo_vagon": fechas[-1] if fechas else None, "area_ef": area, "ton": ton, "n_vagones": len(vag),
            "tch_real": ton / area if area else None, "tch_ppto": c["tch_ppto"], "tch_anterior": c["tch_anterior"],
        })
    return out


_COLS_AFORO = ("id,suerte,date,numero_corte,tch_pesos,tch_modelo,tch_modelo_std,modelo_corrida,modelo_fecha_corte,"
               "desv_modelo")


def aforos() -> list[dict]:
    """Aforos del módulo de Evaluaciones con el estimado del modelo que guardó cada uno (sin datos personales)."""
    url, key = _credenciales()
    return _todo(url, key, "aforo_records", {"select": _COLS_AFORO})
