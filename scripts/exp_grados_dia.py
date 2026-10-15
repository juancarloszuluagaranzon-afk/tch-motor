"""TAREA A — ¿La edad TÉRMICA (grados-día) mejora el estimador de TCH?

Hipótesis: complementar/reemplazar la edad-calendario (meses) por grados-día
acumulados (GDD) deja al RF normalizar el NDVI por fenología real y captar
campañas más frías/cálidas.

Diseño de validación = campaña cerrada: GroupKFold(5) agrupando por año de
cosecha (nunca split aleatorio). Métricas: MAE (t/ha), MAPE (%), ±10%, ±20%.

Fuente de temperatura: NASA POWER API (T2M_MAX, T2M_MIN diarios, community AG),
gratuita y sin auth. GDD_día = max(0, (Tmax+Tmin)/2 - Tbase). Se prueban
Tbase = 18 °C (caña) y 16 °C. Coordenada por suerte = centroide del catálogo de
tablones (lat/lon por tab_id). Cacheado por celda POWER (redondeo 0.25°) y rango
completo, para no repetir llamadas.

Uso:
    PYTHONUTF8=1 python scripts/exp_grados_dia.py
"""
from __future__ import annotations
import io, sys, os, json, time, urllib.request
from datetime import date
import numpy as np, pandas as pd, openpyxl
from sklearn.model_selection import GroupKFold

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
from tchmotor import cargar_var_map, AforoSintetico, build_features, MotorTCH

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DS = r"C:\Users\Agr349\tch-motor\data\dataset_entrenamiento.jsonl"
AFORO = r"C:\Users\Agr349\Documents\Base de aforos completa 2026.xlsx"
CAT_RIO = r"C:\Users\Agr349\agrocontrol-campo\public\data\tablones_catalogo.json"
CAT_CAS = r"C:\Users\Agr349\agrocontrol-campo\public\data\tablones_castilla_catalogo.json"
CACHE = os.path.join(
    os.environ.get("TMP", "."),
    "claude", "C--Users-Agr349",
    "b8086a2a-b9e9-4689-9102-380331880077", "scratchpad", "power_cache.json",
)
POWER = ("https://power.larc.nasa.gov/api/temporal/daily/point"
         "?parameters=T2M,T2M_MAX,T2M_MIN&community=AG"
         "&latitude={lat}&longitude={lon}&start={s}&end={e}&format=JSON")
GRID = 0.25  # ° — celda de cacheo (POWER es ~0.5°; redondear no cambia el dato)


# --- aforo (idéntico al baseline; reproduce el vector de features) -----------
def num(x):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return np.nan


def registros_aforo():
    wb = openpyxl.load_workbook(AFORO, read_only=True, data_only=True)
    out = []
    for name in ["Aforos 2024-2026", "GENERAL DE LA SUERTE", "BASE 2022-2023", "AFOROS 2022-2023"]:
        if name not in wb.sheetnames:
            continue
        rows = list(wb[name].iter_rows(values_only=True, max_col=34))
        hi = next((i for i, r in enumerate(rows[:6]) if any(str(c).strip().upper() == "VARIEDAD" for c in r if c)), None)
        if hi is None:
            continue
        H = {str(c).strip().lower(): j for j, c in enumerate(rows[hi]) if c}
        fnd = lambda *s: next((j for k, j in H.items() if all(x in k for x in s)), None)
        cv, cc, cpob, ctch = fnd("variedad"), fnd("corte"), fnd("tallos", "mt"), fnd("tch", "calcul")
        cpe, cdi = fnd("total", "peso"), fnd("total", "diam")
        if cv is None or cpob is None:
            continue
        for r in rows[hi + 1:]:
            var = str(r[cv]).strip() if r[cv] else None
            pob = num(r[cpob])
            if not var or not (var.startswith("CC") or var == "VARIAS") or not (3 < pob < 25):
                continue
            out.append(dict(variedad=var, soca=num(r[cc]) if cc is not None else None,
                            pob=pob, peso=num(r[cpe]) if cpe else None,
                            dia=num(r[cdi]) if cdi else None,
                            tch=num(r[ctch]) if ctch else None))
    wb.close()
    return out


# --- coordenadas por tab_id --------------------------------------------------
def coords_por_tab():
    d = {}
    for path in (CAT_RIO, CAT_CAS):
        for c in json.load(open(path, encoding="utf-8")):
            if "lat" in c and "lon" in c:
                d[c["tab_id"]] = (float(c["lat"]), float(c["lon"]))
    return d


def celda(lat, lon, g=GRID):
    return (round(round(lat / g) * g, 2), round(round(lon / g) * g, 2))


# --- NASA POWER (cache por celda, rango completo) ----------------------------
def cargar_cache():
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))
    return {}


def guardar_cache(c):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(c, open(CACHE, "w", encoding="utf-8"))


def fetch_power(lat, lon, s, e, reintentos=5):
    url = POWER.format(lat=lat, lon=lon, s=s, e=e)
    for i in range(reintentos):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                d = json.loads(r.read().decode())
            p = d["properties"]["parameter"]
            return {"TMAX": p["T2M_MAX"], "TMIN": p["T2M_MIN"]}
        except Exception as ex:
            if i == reintentos - 1:
                raise
            time.sleep(3 * (i + 1))
    return None


def serie_diaria_temp(eventos, coords):
    """{celda: {'TMAX':{YYYYMMDD:val},'TMIN':...}} para el rango global."""
    span_ini = min(e["cut"] for e in eventos).replace("-", "")
    span_fin = max(e["harvest"] for e in eventos).replace("-", "")
    cache = cargar_cache()
    necesarias = set()
    for e in eventos:
        if e["tab_id"] in coords:
            necesarias.add(celda(*coords[e["tab_id"]]))
    for (clat, clon) in sorted(necesarias):
        key = f"{clat},{clon},{span_ini},{span_fin}"
        if key in cache:
            continue
        print(f"  POWER fetch celda {clat},{clon} {span_ini}-{span_fin} ...", flush=True)
        cache[key] = fetch_power(clat, clon, span_ini, span_fin)
        guardar_cache(cache)
    return cache, span_ini, span_fin


def gdd_evento(ev, coords, cache, span_ini, span_fin, base):
    """GDD acumulados de cut..harvest con Tbase. NaN si no hay coord/temp."""
    if ev["tab_id"] not in coords:
        return float("nan")
    clat, clon = celda(*coords[ev["tab_id"]])
    key = f"{clat},{clon},{span_ini},{span_fin}"
    rec = cache.get(key)
    if not rec:
        return float("nan")
    tmax, tmin = rec["TMAX"], rec["TMIN"]
    d0 = date.fromisoformat(ev["cut"][:10])
    d1 = date.fromisoformat(ev["harvest"][:10])
    total = 0.0
    n = 0
    dd = d0
    from datetime import timedelta
    while dd <= d1:
        k = dd.strftime("%Y%m%d")
        a, b = tmax.get(k), tmin.get(k)
        if a is not None and b is not None and a > -100 and b > -100:
            gdd = max(0.0, (a + b) / 2 - base)
            total += gdd
            n += 1
        dd += timedelta(days=1)
    return total if n > 0 else float("nan")


# --- validación --------------------------------------------------------------
def cv_pred(df, y, g, n=600):
    pred = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(df, y, g):
        m = MotorTCH(n_estimators=n).entrenar(df.iloc[tr], y[tr])
        pred[te] = m.predecir(df.iloc[te])
    return pred


def met(pred, y):
    e = np.abs(pred - y)
    ape = e / y * 100
    return e.mean(), ape.mean(), (ape < 10).mean() * 100, (ape < 20).mean() * 100


def fila(lbl, m, n=None):
    ns = f"{n:>4}" if n is not None else "    "
    print(f"{lbl:<22} {ns} | MAE {m[0]:>5.1f}t  MAPE {m[1]:>4.1f}%  "
          f"±10% {m[2]:>4.0f}%  ±20% {m[3]:>4.0f}%")


def main():
    vm = cargar_var_map()
    sint = AforoSintetico(registros_aforo(), min_n=4)
    coords = coords_por_tab()
    eventos = [json.loads(l) for l in open(DS, encoding="utf-8")]
    print(f"eventos: {len(eventos)} | con coord por tab_id: "
          f"{sum(1 for e in eventos if e['tab_id'] in coords)}")

    cache, s0, s1 = serie_diaria_temp(eventos, coords)

    # Features baseline + columnas GDD, en el mismo orden.
    feats, y, g, edad_real, gb18, gb16 = [], [], [], [], [], []
    for r in eventos:
        f = build_features(r, sint, vm, max_age=None)
        if f.get("ndvi_n", 0) < 3:
            continue
        g18 = gdd_evento(r, coords, cache, s0, s1, 18.0)
        g16 = gdd_evento(r, coords, cache, s0, s1, 16.0)
        feats.append(f)
        y.append(r["tch"]); g.append(int(r["anio"]))
        edad_real.append(float(r["edad"]))
        gb18.append(g18); gb16.append(g16)
    df = pd.DataFrame(feats)
    y = np.array(y); g = np.array(g)
    edad_real = np.array(edad_real)
    gb18 = np.array(gb18); gb16 = np.array(gb16)

    cov = np.mean(np.isfinite(gb18)) * 100
    print(f"eventos usados: {len(y)} | cobertura GDD: {cov:.0f}%")
    print(f"GDD b18: media {np.nanmean(gb18):.0f}  rango [{np.nanmin(gb18):.0f}, {np.nanmax(gb18):.0f}]")
    print(f"GDD b16: media {np.nanmean(gb16):.0f}  rango [{np.nanmin(gb16):.0f}, {np.nanmax(gb16):.0f}]")
    print(f"edad calendario: media {edad_real.mean():.1f}  rango [{edad_real.min():.1f}, {edad_real.max():.1f}] meses")
    # correlación GDD vs edad-calendario (si es ~1, GDD no aporta info nueva)
    fin = np.isfinite(gb18)
    print(f"corr(GDD_b18, edad_cal) = {np.corrcoef(gb18[fin], edad_real[fin])[0,1]:.2f}")
    print(f"corr(GDD_b18, TCH)      = {np.corrcoef(gb18[fin], y[fin])[0,1]:.2f}")
    print(f"corr(edad_cal, TCH)     = {np.corrcoef(edad_real, y)[0,1]:.2f}")

    # velocidad térmica (GDD por mes de edad)
    gpm18 = gb18 / np.where(edad_real > 0, edad_real, np.nan)

    print("\n=== CICLO COMPLETO (max_age=None), GroupKFold-por-año ===")
    base = cv_pred(df, y, g)
    fila("baseline (edad cal)", met(base, y), len(y))

    dfc = df.copy(); dfc["gdd_b18"] = gb18
    fila("+ GDD b18", met(cv_pred(dfc, y, g), y))

    dfc16 = df.copy(); dfc16["gdd_b16"] = gb16
    fila("+ GDD b16", met(cv_pred(dfc16, y, g), y))

    dfcv = df.copy(); dfcv["gdd_b18"] = gb18; dfcv["gdd_por_mes"] = gpm18
    fila("+ GDD b18 + vel.term", met(cv_pred(dfcv, y, g), y))

    # reemplazar edad-calendario por edad-térmica
    dfr = df.drop(columns=["edad"]).copy(); dfr["gdd_b18"] = gb18
    fila("reemplaza edad->GDD", met(cv_pred(dfr, y, g), y))

    dfr16 = df.drop(columns=["edad"]).copy(); dfr16["gdd_b16"] = gb16
    fila("reemplaza edad->GDD16", met(cv_pred(dfr16, y, g), y))

    # --- por banda de edad-calendario de cosecha (donde la hipótesis apunta:
    #     misma edad calendario, distinta acumulación térmica) ---
    print("\n=== por BANDA de edad-calendario (ciclo completo) ===")
    bandas = [("<11.5m", edad_real < 11.5),
              ("11.5-13m", (edad_real >= 11.5) & (edad_real <= 13)),
              (">13m", edad_real > 13)]
    pred_b = cv_pred(df, y, g)
    dfc2 = df.copy(); dfc2["gdd_b18"] = gb18
    pred_g = cv_pred(dfc2, y, g)
    for nb, mask in bandas:
        if mask.sum() < 20:
            print(f"{nb}: n={mask.sum()} (muy pocos, se omite)")
            continue
        print(f"-- {nb}  (n={mask.sum()}) --")
        fila("  baseline", met(pred_b[mask], y[mask]))
        fila("  + GDD b18", met(pred_g[mask], y[mask]))

    # --- proyección de caña joven: truncar curva Y GDD a la edad A ---
    print("\n=== PROYECCIÓN caña joven (curva y GDD truncadas a la edad A) ===")
    for A in [6, 9]:
        feats_a, y_a, g_a, gdd_a = [], [], [], []
        for r in eventos:
            rec = dict(r)
            rec["edad"] = A
            cm = int(str(r["cut"])[5:7])
            rec["mes"] = ((cm - 1 + int(round(A))) % 12) + 1
            f = build_features(rec, sint, vm, max_age=A)
            if f.get("ndvi_n", 0) < 3:
                continue
            # GDD acumulado de cut hasta cut+A meses (truncado, sin fuga)
            from datetime import timedelta
            d0 = date.fromisoformat(r["cut"][:10])
            dA = d0 + timedelta(days=int(A * 30.44))
            rec2 = dict(r); rec2["harvest"] = dA.isoformat()
            gdd_a.append(gdd_evento(rec2, coords, cache, s0, s1, 18.0))
            feats_a.append(f); y_a.append(r["tch"]); g_a.append(int(r["anio"]))
        dfa = pd.DataFrame(feats_a); ya = np.array(y_a); ga = np.array(g_a)
        gdd_a = np.array(gdd_a)
        print(f"-- edad proyección {A}m  (n={len(ya)}) --")
        fila("  baseline", met(cv_pred(dfa, ya, ga), ya))
        dfag = dfa.copy(); dfag["gdd_b18"] = gdd_a
        fila("  + GDD b18", met(cv_pred(dfag, ya, ga), ya))


if __name__ == "__main__":
    main()
