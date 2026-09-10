"""Demo/aceptación de P0: usa el MÓDULO tchmotor sobre los datos reales y
comprueba que reproduce el resultado validado (R²≈0.50, MAPE≈13.6%).

Datos de la sesión (rutas absolutas; en producción vendrán de Supabase/CDSE).
"""
import io, sys, json, numpy as np, pandas as pd, openpyxl
from sklearn.model_selection import GroupKFold

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
from tchmotor import cargar_var_map, AforoSintetico, build_features, MotorTCH  # noqa

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SCR = r"C:\Users\Agr349\AppData\Local\Temp\claude\C--Users-Agr349\c35094b4-9666-4a90-b2bc-c7d6f1f9f236\scratchpad"
AFORO = r"C:\Users\Agr349\Documents\Base de aforos completa 2026.xlsx"


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


vm = cargar_var_map()
sint = AforoSintetico(registros_aforo(), min_n=4)
rows = []
for line in open(SCR + r"\curves.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if not r["curves"].get("NDVI"):
        continue
    f = build_features(r, sint, vm)
    if f["ndvi_n"] < 3:
        continue
    f["tch"] = r["tch"]
    f["anio"] = r["anio"]
    rows.append(f)
df = pd.DataFrame(rows)
y = df["tch"].values
g = df["anio"].values
X = df.drop(columns=["tch", "anio"])

# validación por año (campaña cerrada), con el MotorTCH del paquete
pred = np.zeros(len(y))
for tr, te in GroupKFold(5).split(X, y, g):
    m = MotorTCH(n_estimators=600).entrenar(X.iloc[tr], y[tr])
    pred[te] = m.predecir(X.iloc[te])
e = pred - y
ape = np.abs(e) / y * 100
r2 = 1 - (e ** 2).sum() / ((y - y.mean()) ** 2).sum()
print(f"n={len(y)}  R²={r2:+.2f}  MAPE={ape.mean():.1f}%  ±20%={(ape<20).mean()*100:.0f}%")
print("→ P0 OK: el módulo reproduce el resultado validado." if r2 > 0.45 else "→ REVISAR")
