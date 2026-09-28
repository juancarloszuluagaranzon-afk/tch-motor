"""Seed de las tablas de referencia en el Supabase de Rio Map:
  - tch_var_map        ← data/var_map.json
  - tch_aforo_sintetico ← base de aforos (mediana de tallos por variedad×soca)

Requiere TCH_SUPABASE_URL y TCH_SUPABASE_KEY (service_role) en el entorno, y la
migración sql/0001_tch_esquema.sql ya aplicada. Recompute periódico (trimestral).
"""
import io, sys

sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
from tchmotor import cargar_var_map, AforoSintetico, Supabase  # noqa
from tchmotor.aforo import registros_aforo_excel  # noqa

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
AFORO = r"C:\Users\Agr349\Documents\Base de aforos completa 2026.xlsx"


def registros_aforo():
    return registros_aforo_excel(AFORO)


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
