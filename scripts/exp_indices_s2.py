"""TAREA C — ¿Aportan los índices S2 nuevos (NDRE/SAVI/CI-RE/GNDVI) al TCH?

Mide el valor INCREMENTAL de las curvas de los índices de borde rojo / ajuste de
suelo / verde sobre el baseline (NDVI+NDMI+EVI + agronomía + aforo sintético),
con GroupKFold(5) por año y partido por banda de edad de proyección.

    >>> REQUIERE EL DEPLOY DE LA TAREA B <<<
El endpoint https://riomap.vercel.app/api/sentinel-stats solo devuelve estos
índices una vez desplegada la rama `feat/sentinel-indices-s2` (STAT_INDEXES +
FORMULA extendidos en lib/geo/sentinelStats.ts). Antes del deploy, el endpoint
responde 400 (`error:"params"`) para index=NDRE/SAVI/CI-RE/GNDVI y este script
lo detecta y aborta con un mensaje claro (no inventa datos).

Las curvas nuevas se piden en vivo (504 eventos × 4 índices = ~2016 llamadas) y
se CACHEAN en disco; reejecutar es barato. Pensado para correr POST-deploy.

Uso (tras desplegar la Tarea B):
    PYTHONUTF8=1 python scripts/exp_indices_s2.py
    PYTHONUTF8=1 python scripts/exp_indices_s2.py --indices NDRE SAVI
"""
from __future__ import annotations
import io, sys, os, json, argparse
import numpy as np, pandas as pd, openpyxl
from sklearn.model_selection import GroupKFold

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
from tchmotor import (
    cargar_var_map, AforoSintetico, build_features, MotorTCH,
    curve_pairs, curve_features, serie_indice, RIOMAP_ENDPOINT,
)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DS = r"C:\Users\Agr349\tch-motor\data\dataset_entrenamiento.jsonl"
AFORO = r"C:\Users\Agr349\Documents\Base de aforos completa 2026.xlsx"
CACHE = os.path.join(
    os.environ.get("TMP", "."),
    "claude", "C--Users-Agr349",
    "b8086a2a-b9e9-4689-9102-380331880077", "scratchpad", "s2_indices_cache.json",
)
NUEVOS = ["NDRE", "SAVI", "CI-RE", "GNDVI"]


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


# --- descarga + cache de las curvas de índices nuevos ------------------------
def cargar_cache():
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))
    return {}


def guardar_cache(c):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(c, open(CACHE, "w", encoding="utf-8"))


def _probe_endpoint(ev0, index):
    """Comprueba que el endpoint acepta el índice nuevo (post-deploy Tarea B).
    Devuelve True si responde una serie; False si sigue rechazándolo (400)."""
    s = serie_indice(ev0["tab_id"], ev0["planta"], index,
                     ev0["cut"], ev0["harvest"], reintentos=2)
    return s is not None


def curva_nueva(ev, index, cache):
    key = f"{ev['tab_id']}|{ev['planta']}|{index}|{ev['cut']}|{ev['harvest']}"
    if key in cache:
        return cache[key]
    s = serie_indice(ev["tab_id"], ev["planta"], index, ev["cut"], ev["harvest"])
    if s is not None:
        cache[key] = s
        guardar_cache(cache)
    return s


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
    print(f"{lbl:<24} {ns} | MAE {m[0]:>5.1f}t  MAPE {m[1]:>4.1f}%  "
          f"±10% {m[2]:>4.0f}%  ±20% {m[3]:>4.0f}%")


def feats_nuevos(ev, indices, cache, max_age):
    """curve_features de los índices nuevos para un evento, o None si falta red."""
    out = {}
    for idx in indices:
        serie = curva_nueva(ev, idx, cache)
        if serie is None:
            return None
        pares = curve_pairs(ev["cut"], serie, max_age=max_age)
        # nombre de columna sin caracteres raros (CI-RE -> cire)
        nom = idx.lower().replace("-", "")
        out.update(curve_features(nom, pares))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", nargs="+", default=NUEVOS,
                    help="subconjunto de índices nuevos a probar")
    ap.add_argument("--endpoint", default=RIOMAP_ENDPOINT)
    args = ap.parse_args()
    indices = args.indices

    vm = cargar_var_map()
    sint = AforoSintetico(registros_aforo(), min_n=4)
    eventos = [json.loads(l) for l in open(DS, encoding="utf-8")]
    cache = cargar_cache()

    print(f"Índices a probar: {indices}")
    print(f"Endpoint: {args.endpoint}")
    print("Comprobando que el endpoint ya sirve los índices nuevos "
          "(deploy Tarea B)...")
    for idx in indices:
        if not _probe_endpoint(eventos[0], idx):
            print(f"\n[BLOQUEADO] El endpoint NO devuelve '{idx}'. "
                  "Falta desplegar la rama feat/sentinel-indices-s2 "
                  "(Tarea B) en Vercel. Abortando SIN inventar datos.")
            sys.exit(2)
    print("OK: el endpoint responde los índices nuevos.\n")

    print("=== por BANDA de edad de proyección (curva truncada a la edad A) ===")
    print("baseline = NDVI+NDMI+EVI + agronomía + aforo sintético\n")
    for A in [6, 9, None]:
        feats_base, extra, y, g = [], [], [], []
        faltan = 0
        for r in eventos:
            rec = dict(r)
            if A is not None:
                rec["edad"] = A
                cm = int(str(r["cut"])[5:7])
                rec["mes"] = ((cm - 1 + int(round(A))) % 12) + 1
            fb = build_features(rec, sint, vm, max_age=A)
            if fb.get("ndvi_n", 0) < 3:
                continue
            fn = feats_nuevos(r, indices, cache, A)
            if fn is None:
                faltan += 1
                continue
            feats_base.append(fb); extra.append(fn)
            y.append(r["tch"]); g.append(int(r["anio"]))
        if not y:
            print(f"edad {A}: sin eventos con datos (faltan={faltan}).")
            continue
        dfb = pd.DataFrame(feats_base)
        dfn = pd.concat([dfb, pd.DataFrame(extra)], axis=1)
        y = np.array(y); g = np.array(g)
        lbl = "full" if A is None else f"{A}m"
        print(f"-- edad {lbl}  (n={len(y)}, sin curva nueva={faltan}) --")
        fila("  baseline", met(cv_pred(dfb, y, g), y))
        fila(f"  + {'+'.join(indices)}", met(cv_pred(dfn, y, g), y))


if __name__ == "__main__":
    main()
