# -*- coding: utf-8 -*-
"""Agrega a cosechas_recientes.xlsx las cosechas de Riopaila terminadas en un mes, desde la app de Turnos.

La corrida mensual (scripts/mensual.py) lee ese Excel como complemento del ZQM; sin las cosechas del mes,
el factor de calibración de la campaña no las ve. Castilla no está en la app: sus filas se pegan a mano
(suerte, TCH real, fecha en que terminó el corte).

Antes de escribir guarda un respaldo del Excel en la misma carpeta (uno por día). No duplica: se salta la
suerte que ya tiene una fila con la misma fecha.

Uso:  .venv-gee\\Scripts\\python.exe scripts\\cosechas_desde_app.py --mes 2026-10 [--simular]
"""
import argparse
import calendar
import os
import shutil
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import openpyxl  # noqa: E402

from tchmotor import rutas, turnos  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", required=True, help="AAAA-MM de la fecha de cierre")
    ap.add_argument("--simular", action="store_true", help="muestra lo que agregaría sin escribir")
    a = ap.parse_args()
    y, m = map(int, a.mes.split("-"))
    desde, hasta = f"{a.mes}-01", f"{a.mes}-{calendar.monthrange(y, m)[1]:02d}"
    cortes = [c for c in turnos.cortes_terminados(desde, hasta) if c["tch_real"] is not None]
    print(f"app de Turnos: {len(cortes)} cortes de Riopaila terminados en {a.mes} con TCH")

    arch = rutas.COSECHAS_RECIENTES
    wb = openpyxl.load_workbook(arch)
    ws = wb["Cosechas"]
    ya = {(str(r[0]).strip(), r[2].date() if hasattr(r[2], "date") else r[2])
          for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0]}
    nuevos = [c for c in sorted(cortes, key=lambda x: (x["fecha_fin"], x["sec_ste"]))
              if (c["sec_ste"], date.fromisoformat(c["fecha_fin"])) not in ya]
    for c in nuevos:
        print(f"  {c['sec_ste']}  TCH {c['tch_real']:.2f}  termina {c['fecha_fin']}")
    if a.simular or not nuevos:
        print("nada escrito" + (" (simulación)" if a.simular else ": ya estaban todas"))
        return
    resp = arch.with_name(f"{arch.stem}_respaldo_{date.today().isoformat()}{arch.suffix}")
    if not resp.exists():
        shutil.copy2(arch, resp)
        print("respaldo:", resp.name)
    for c in nuevos:
        k = ws.max_row + 1
        ws.cell(k, 1, c["sec_ste"])
        ws.cell(k, 2, round(c["tch_real"], 2))
        ws.cell(k, 3, datetime.fromisoformat(c["fecha_fin"])).number_format = "d/mm/yyyy"
    wb.save(arch)
    print(f"agregadas {len(nuevos)} cosechas · {arch}")


if __name__ == "__main__":
    main()
