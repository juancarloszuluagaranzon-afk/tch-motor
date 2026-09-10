"""Seed de las tablas de referencia en el Supabase de Rio Map:
  - tch_var_map        ← data/var_map.json
  - tch_aforo_sintetico ← base de aforos (mediana de tallos por variedad×soca)

Requiere TCH_SUPABASE_URL y TCH_SUPABASE_KEY (service_role) en el entorno, y la
migración sql/0001_tch_esquema.sql ya aplicada. Recompute periódico (trimestral).
"""
import io, sys, numpy as np, openpyxl

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
from tchmotor import cargar_var_map, AforoSintetico, Supabase  # noqa

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
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


def _limpio(filas):
    # numpy NaN → None para que PostgREST lo acepte como null
    out = []
    for f in filas:
        out.append({k: (None if (isinstance(v, float) and v != v) else v) for k, v in f.items()})
    return out


def main():
    sb = Supabase()  # lee TCH_SUPABASE_URL / TCH_SUPABASE_KEY del entorno
    vm = cargar_var_map()
    n1 = sb.upsert("tch_var_map", [{"codigo": k, "nombre": v} for k, v in vm.items()], "codigo")
    print(f"tch_var_map: {n1} variedades")
    sint = AforoSintetico(registros_aforo(), min_n=4)
    n2 = sb.guardar_aforo_sintetico(_limpio(sint.filas()))
    print(f"tch_aforo_sintetico: {n2} filas (variedad×soca + respaldo por variedad)")


if __name__ == "__main__":
    main()
