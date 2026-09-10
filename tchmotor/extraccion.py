"""Cliente de extracción de curvas satelitales (opción A: endpoint de Rio Map).

Llama a `/api/sentinel-stats?interval=P30D` de Rio Map (ya desplegado, con su
OAuth) y devuelve la serie mensual de un índice sobre un tablón. Encapsula las
lecciones aprendidas:
  - `interval=P30D` → la curva completa en UNA llamada;
  - `maxcc=60` + SCL enmascara nubes por píxel;
  - reintentos con espera ante errores/rate-limit y **sin cachear** el error;
  - respuesta con `stats:null` (nube) o `"NaN"` se traduce a `mean=None`.

La función de red acepta un `abrir` inyectable para poder testear sin red.
A mediano plazo esto se puede reemplazar por una integración CDSE propia
(opción B) sin tocar el resto del motor.
"""
from __future__ import annotations
import json
import time
import urllib.request
import urllib.parse

RIOMAP_ENDPOINT = "https://riomap.vercel.app/api/sentinel-stats"


def build_url(base, tab_id, planta, index, cut, harvest, interval="P30D", maxcc=60) -> str:
    """URL de la petición de serie temporal para un índice sobre un tablón."""
    q = urllib.parse.urlencode(
        {
            "tab_id": tab_id,
            "planta": planta,
            "index": index,
            "maxcc": maxcc,
            "interval": interval,
            "from": cut,
            "to": harvest,
        }
    )
    return f"{base}?{q}"


def _mean(punto: dict):
    """Media finita del punto, o None (nube/sin dato/'NaN')."""
    st = punto.get("stats")
    if not st:
        return None
    m = st.get("mean")
    try:
        m = float(m)
    except (TypeError, ValueError):
        return None
    return m if m == m else None  # descarta NaN


def parse_series(payload: dict):
    """`{series:[{from,stats}]}` → `[{from, mean}]` (mean None si nube/NaN)."""
    return [
        {"from": p.get("from"), "mean": _mean(p)}
        for p in (payload.get("series") or [])
    ]


def serie_indice(
    tab_id,
    planta,
    index,
    cut,
    harvest,
    *,
    base=RIOMAP_ENDPOINT,
    interval="P30D",
    maxcc=60,
    pausa=0.4,
    timeout=120,
    reintentos=6,
    abrir=urllib.request.urlopen,
    dormir=time.sleep,
):
    """Serie mensual de un índice, o None si la red falla tras los reintentos."""
    url = build_url(base, tab_id, planta, index, cut, harvest, interval, maxcc)
    for intento in range(reintentos):
        try:
            with abrir(url, timeout=timeout) as r:
                payload = json.loads(r.read().decode())
            if "series" not in payload:  # error/rate-limit → reintenta, NO cachea
                dormir(3 * (intento + 1))
                continue
            dormir(pausa)
            return parse_series(payload)
        except Exception:
            dormir(3 * (intento + 1))
    return None


def curva_suerte(
    tab_id, planta, cut, harvest, indices=("NDVI", "NDMI", "EVI"), **kw
):
    """Dict índice→serie de un tablón. None si algún índice falla en red."""
    curves = {}
    for idx in indices:
        s = serie_indice(tab_id, planta, idx, cut, harvest, **kw)
        if s is None:
            return None
        curves[idx] = s
    return curves
