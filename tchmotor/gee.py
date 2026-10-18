"""Extracción de índices satelitales con Google Earth Engine (alternativa a Rio Map/Copernicus).

Dos modos:

* `serie_ventanas`: replica la receta de Rio Map (`agrocontrol-campo/lib/geo/sentinelStats.ts`)
  para poder comparar punto contra punto con las curvas ya guardadas: Sentinel-2 L2A, escenas con
  nube de tesela <= `maxcc`, ventanas de 30 días desde el corte, mosaico "más reciente" dentro de la
  ventana, máscara de nubes por píxel con la SCL (después del mosaico, como Sentinel Hub) y media
  sobre el polígono a 10 m.
* `tabla_mensual`: una fila por suerte y mes calendario para todas las suertes de una planta a la
  vez (óptico con máscara SCL por imagen + mediana del mes, y radar Sentinel-1 en dB). Es la que
  sirve para comparar años y para el reentrenamiento; no pretende paridad exacta con Rio Map.

Credenciales: `GEE_PROJECT` (id del proyecto de Google Cloud) y `GEE_KEY_FILE` (ruta a la llave JSON
de la cuenta de servicio), en variables de entorno o en `tch-motor/.env.local`. La app empaquetada pasa
el contenido de la llave en `GEE_KEY_JSON` (la guarda cifrada y nunca la escribe en disco en claro).
La llave nunca se copia al repositorio ni se imprime.
"""
from __future__ import annotations

import datetime as dt
import json
import os

import ee

from . import rutas

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(RAIZ, ".env.local")
TABLONES = str(rutas.TABLONES_DIR / "tablones_{planta}.geojson")

S2 = "COPERNICUS/S2_SR_HARMONIZED"
S1 = "COPERNICUS/S1_GRD"
ERA5 = "ECMWF/ERA5_LAND/DAILY_AGGR"  # reanálisis diario ~11 km, ~1 semana de rezago
CLIMA = ["tmax", "tmin", "lluvia", "hr"]
# SCL que Rio Map descarta: sin dato/defecto, sombra, nube media/alta, cirro, nieve.
SCL_MALOS = [0, 1, 3, 8, 9, 10, 11]
OPTICOS = ["NDVI", "NDMI", "EVI", "NDRE", "SAVI", "GNDVI"]


# ---------------------------------------------------------------- credenciales
def _env(clave: str):
    v = os.environ.get(clave)
    if v:
        return v.strip()
    if os.path.exists(ENV):
        for linea in open(ENV, encoding="utf-8"):
            linea = linea.strip()
            if linea.startswith(clave + "="):
                return linea.split("=", 1)[1].strip().strip('"') or None
    return None


def iniciar():
    """Inicia Earth Engine. Devuelve (proyecto, identidad usada).

    Con cuenta de servicio si `GEE_KEY_FILE` apunta a una llave que existe; si no, con las credenciales
    del usuario guardadas por `earthengine authenticate` (plan B cuando la organización no permite llaves).
    """
    proyecto, llave = _env("GEE_PROJECT"), _env("GEE_KEY_FILE")
    if not proyecto:
        raise RuntimeError("Falta GEE_PROJECT en tch-motor/.env.local")
    contenido = os.environ.get("GEE_KEY_JSON")
    if contenido:
        correo = json.loads(contenido).get("client_email")
        ee.Initialize(ee.ServiceAccountCredentials(correo, key_data=contenido), project=proyecto)
        return proyecto, correo
    if llave and os.path.exists(llave):
        correo = json.load(open(llave, encoding="utf-8")).get("client_email")
        ee.Initialize(ee.ServiceAccountCredentials(correo, llave), project=proyecto)
        return proyecto, correo
    ee.Initialize(project=proyecto)  # credenciales de usuario (earthengine authenticate)
    return proyecto, "credenciales de usuario"


# ---------------------------------------------------------------- geometrías
_CACHE_GEO: dict = {}


def _features(planta: str):
    planta = planta.lower()
    if planta not in _CACHE_GEO:
        _CACHE_GEO[planta] = json.load(open(TABLONES.format(planta=planta), encoding="utf-8"))["features"]
    return _CACHE_GEO[planta]


def _poligonos(geom: dict):
    """Lista de polígonos (anillos) de una geometría GeoJSON Polygon/MultiPolygon."""
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return list(geom["coordinates"])
    return []


def coords_tablon(tab_id: str, planta: str):
    for f in _features(planta):
        if f["properties"].get("tab_id") == tab_id:
            return _poligonos(f["geometry"])
    return None


def coords_suertes(planta: str):
    """{sec_ste: [polígonos de todos sus tablones]} para una planta."""
    out: dict = {}
    for f in _features(planta):
        s = f["properties"].get("sec_ste")
        if s:
            out.setdefault(s, []).extend(_poligonos(f["geometry"]))
    return out


def centroides_suertes(planta: str):
    """{sec_ste: (lon, lat)} promedio de los vértices de sus tablones (basta para una grilla de 11 km)."""
    out = {}
    for s, pols in coords_suertes(planta).items():
        pts = [p for pol in pols for p in pol[0]]
        if pts:
            out[s] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    return out


def geom_ee(poligonos):
    return ee.Geometry.MultiPolygon(poligonos, None, False)


# ---------------------------------------------------------------- índices
def _indices(img):
    """Índices ópticos con las fórmulas de Rio Map, sobre reflectancia 0-1."""
    r = img.select(["B2", "B3", "B4", "B5", "B8", "B11"]).divide(10000)
    B = {b: r.select(b) for b in ["B2", "B3", "B4", "B5", "B8", "B11"]}
    ndvi = B["B8"].subtract(B["B4"]).divide(B["B8"].add(B["B4"])).rename("NDVI")
    ndmi = B["B8"].subtract(B["B11"]).divide(B["B8"].add(B["B11"])).rename("NDMI")
    evi = r.expression("2.5 * (B8 - B4) / (B8 + 6.0 * B4 - 7.5 * B2 + 1.0)",
                       {"B8": B["B8"], "B4": B["B4"], "B2": B["B2"]}).rename("EVI")
    # Con bruma o nube que la SCL no marca el denominador se acerca a 0 y el EVI se dispara
    # (paridad: una ventana con media -1,60). Esos píxeles no son vegetación medible.
    evi = evi.updateMask(evi.gte(-1).And(evi.lte(1)))
    ndre = B["B8"].subtract(B["B5"]).divide(B["B8"].add(B["B5"])).rename("NDRE")
    savi = r.expression("1.5 * (B8 - B4) / (B8 + B4 + 0.5)", {"B8": B["B8"], "B4": B["B4"]}).rename("SAVI")
    gndvi = B["B8"].subtract(B["B3"]).divide(B["B8"].add(B["B3"])).rename("GNDVI")
    return ee.Image.cat([ndvi, ndmi, evi, ndre, savi, gndvi])


def _despejado(img):
    """1 donde la SCL no es nube/sombra/cirro/nieve/sin dato; 0 en el resto."""
    return img.select("SCL").remap(SCL_MALOS, [0] * len(SCL_MALOS), 1)


def _vacia(bandas):
    return ee.Image.constant([0] * len(bandas)).rename(bandas).updateMask(ee.Image.constant(0))


# ---------------------------------------------------------------- modo 1: ventanas como Rio Map
def ventanas(corte: str, cosecha: str, dias: int = 30):
    # Como la Statistical API de Sentinel Hub: solo ventanas completas; la última, si no cabe entera
    # antes del fin del día de cosecha, se descarta.
    d, h = dt.date.fromisoformat(corte[:10]), dt.date.fromisoformat(cosecha[:10])
    out = []
    while d + dt.timedelta(days=dias) <= h + dt.timedelta(days=1):
        out.append(d.isoformat())
        d += dt.timedelta(days=dias)
    return out


def serie_ventanas(poligonos, corte: str, cosecha: str, dias: int = 30, maxcc: int = 60,
                   indices=("NDVI", "NDMI", "EVI")):
    """Serie por ventanas de `dias` desde el corte, receta de Rio Map. Una sola llamada al servidor."""
    geom = geom_ee(poligonos)
    base = ee.ImageCollection(S2).filterBounds(geom).filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", maxcc))
    bandas = list(indices)

    def por_ventana(ini):
        ini = ee.Date(ini)
        fin = ini.advance(dias, "day")
        col = base.filterDate(ini, fin).sort("system:time_start")  # ascendente: la más reciente queda arriba
        mos = col.mosaic()
        img = ee.Image(ee.Algorithms.If(col.size().gt(0),
                                        _indices(mos).select(bandas).updateMask(_despejado(mos)),
                                        _vacia(bandas)))
        media = img.reduceRegion(ee.Reducer.mean(), geom, 10, maxPixels=1e9)
        n = img.select(bandas[0]).reduceRegion(ee.Reducer.count(), geom, 10, maxPixels=1e9).get(bandas[0])
        return ee.Feature(None, media.set("from", ini.format("YYYY-MM-dd")).set("escenas", col.size()).set("pixeles", n))

    fc = ee.FeatureCollection(ee.List(ventanas(corte, cosecha, dias)).map(por_ventana))
    return [f["properties"] for f in fc.getInfo()["features"]]


# ---------------------------------------------------------------- modo 2: tabla mensual de todas las suertes
def _compuesto_optico(geom, ini, fin, maxcc: int = 80):
    col = (ee.ImageCollection(S2).filterBounds(geom).filterDate(ini, fin)
           .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", maxcc))
           .map(lambda im: _indices(im).updateMask(_despejado(im))))
    return ee.Image(ee.Algorithms.If(col.size().gt(0), col.median(), _vacia(OPTICOS))), col.size()


def _compuesto_radar(geom, ini, fin):
    col = (ee.ImageCollection(S1).filterBounds(geom).filterDate(ini, fin)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
           .select(["VV", "VH"]))

    def lineal(im):  # S1_GRD de Earth Engine ya viene en dB
        return ee.Image(10).pow(im.divide(10)).copyProperties(im, ["system:time_start"])

    def armar():
        db = col.mean()
        lin = col.map(lineal).mean()
        rvi = lin.expression("4 * VH / (VV + VH)", {"VV": lin.select("VV"), "VH": lin.select("VH")}).rename("RVI")
        return db.select(["VV", "VH"]).addBands(rvi)

    return ee.Image(ee.Algorithms.If(col.size().gt(0), armar(), _vacia(["VV", "VH", "RVI"]))), col.size()


def ultimo_dia_clima() -> str:
    """Último día con ERA5-Land publicado (AAAA-MM-DD)."""
    im = ee.ImageCollection(ERA5).sort("system:time_start", False).first()
    return ee.Date(im.get("system:time_start")).format("YYYY-MM-dd").getInfo()


def _clima_mes(anio: int, mes: int):
    """Imagen con tmax/tmin medias (°C), lluvia (mm) y humedad relativa media (%) del mes."""
    ini = ee.Date.fromYMD(anio, mes, 1)
    col = ee.ImageCollection(ERA5).filterDate(ini, ini.advance(1, "month"))

    def hr(im):  # Magnus con la temperatura y el punto de rocío medios del día
        t = im.select("temperature_2m").subtract(273.15)
        td = im.select("dewpoint_temperature_2m").subtract(273.15)
        e = td.multiply(17.625).divide(td.add(243.04)).exp()
        es = t.multiply(17.625).divide(t.add(243.04)).exp()
        return e.divide(es).multiply(100).rename("hr")

    sfx = f"_{mes:02d}"
    return ee.Image.cat([
        col.select("temperature_2m_max").mean().subtract(273.15).rename("tmax" + sfx),
        col.select("temperature_2m_min").mean().subtract(273.15).rename("tmin" + sfx),
        col.select("total_precipitation_sum").sum().multiply(1000).rename("lluvia" + sfx),
        col.map(hr).mean().rename("hr" + sfx),
    ]), col.size()


def tabla_clima_anual(centroides: dict, anio: int, hasta: str | None = None):
    """Clima mensual por suerte de un año (una llamada al servidor). Filas: sec_ste, anio, mes,
    tmax, tmin, lluvia, hr, dias (días de ERA5 en el mes; < días del mes = mes incompleto)."""
    ultimo = dt.date.fromisoformat(hasta) if hasta else dt.date(anio, 12, 31)
    meses = [m for m in range(1, 13) if dt.date(anio, m, 1) <= ultimo]
    if not meses:
        return []
    imgs, dias = zip(*[_clima_mes(anio, m) for m in meses])
    img = ee.Image.cat(list(imgs))
    fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Point(list(xy)), {"sec_ste": s}) for s, xy in centroides.items()])
    red = img.reduceRegions(collection=fc, reducer=ee.Reducer.first(), scale=11132)
    n_dias = ee.List(list(dias)).getInfo()
    filas = []
    for f in red.getInfo()["features"]:
        p = f["properties"]
        for m, n in zip(meses, n_dias):
            sfx = f"_{m:02d}"
            filas.append({"sec_ste": p["sec_ste"], "anio": anio, "mes": m, "dias": n,
                          **{k: p.get(k + sfx) for k in CLIMA}})
    return filas


COLS_MENSUAL = ["sec_ste", "anio", "mes"] + OPTICOS + ["VV", "VH", "RVI", "despejado"]
RUTA_MENSUAL = rutas.MENSUAL  # .csv.gz: pandas comprime y descomprime por la extensión


def ultimo_mes(planta: str) -> int | None:
    """Último mes (año·12 + mes − 1) que trae la tabla mensual de la planta; None si no existe."""
    import pandas as pd

    destino = RUTA_MENSUAL.format(planta=planta)
    if not os.path.exists(destino):
        return None
    m = pd.read_csv(destino, usecols=["anio", "mes"])
    return int((m.anio * 12 + m.mes - 1).max()) if len(m) else None


def actualizar_tabla_mensual(planta: str, desde: str, hasta: str, rehacer_desde: str | None = None,
                             radar: bool = True, log=print) -> int:
    """Agrega a data/gee/mensual_<planta>.csv los meses (AAAA-MM) que falten entre `desde` y `hasta`.

    `rehacer_desde` borra y vuelve a extraer los meses desde esa fecha (el último mes suele quedar
    incompleto). Reintenta 3 veces por mes. Devuelve el número de meses agregados."""
    import time

    import pandas as pd

    destino = RUTA_MENSUAL.format(planta=planta)
    prev = pd.read_csv(destino) if os.path.exists(destino) else pd.DataFrame(columns=COLS_MENSUAL)
    t_rehacer = None
    if rehacer_desde:
        yr, mr = map(int, rehacer_desde.split("-"))
        t_rehacer = yr * 12 + mr
    hechos = {(a, b) for a, b in zip(prev.anio, prev.mes) if t_rehacer is None or a * 12 + b < t_rehacer}
    suertes = coords_suertes(planta)
    y, m = map(int, desde.split("-"))
    y2, m2 = map(int, hasta.split("-"))
    nuevos, rehechos = [], set()
    while (y, m) <= (y2, m2):
        if (y, m) not in hechos:
            t0 = time.time()
            for intento in range(3):
                try:
                    filas = tabla_mensual(suertes, y, m, radar=radar)
                    nuevos.append(pd.DataFrame(filas).reindex(columns=COLS_MENSUAL))
                    rehechos.add((y, m))
                    log(f"  {planta} {y}-{m:02d}: {len(filas)} suertes · {time.time() - t0:.0f} s")
                    break
                except Exception as e:
                    log(f"  {planta} {y}-{m:02d} intento {intento + 1} falló: {str(e)[:120]}")
                    time.sleep(10 * (intento + 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    if nuevos:  # solo se reemplazan los meses que sí se volvieron a extraer
        viejo = prev[[(a, b) not in rehechos for a, b in zip(prev.anio, prev.mes)]]
        out = pd.concat([viejo] + nuevos, ignore_index=True).sort_values(["anio", "mes", "sec_ste"])
        out.to_csv(destino, index=False)
    return len(nuevos)


def tabla_mensual(poligonos_por_suerte: dict, anio: int, mes: int, radar: bool = True, lote: int = 400):
    """Media por suerte de los índices del mes calendario. Devuelve lista de dicts (una fila por suerte)."""
    ini = ee.Date.fromYMD(anio, mes, 1)
    fin = ini.advance(1, "month")
    filas = []
    claves = list(poligonos_por_suerte)
    for k in range(0, len(claves), lote):
        feats = [ee.Feature(geom_ee(poligonos_por_suerte[s]), {"sec_ste": s}) for s in claves[k:k + lote]]
        fc = ee.FeatureCollection(feats)
        area = fc.geometry()
        opt, n_opt = _compuesto_optico(area, ini, fin)
        img = opt
        if radar:
            rad, n_rad = _compuesto_radar(area, ini, fin)
            img = opt.addBands(rad)
        img = img.addBands(opt.select("NDVI").mask().rename("despejado"))
        red = img.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=10, tileScale=4)
        for f in red.getInfo()["features"]:
            p = f["properties"]
            p["anio"], p["mes"] = anio, mes
            filas.append(p)
    return filas
