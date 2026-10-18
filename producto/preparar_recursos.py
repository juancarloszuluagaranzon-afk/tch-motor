# -*- coding: utf-8 -*-
"""Junta en producto/recursos lo que va dentro del instalador (no va en git: trae datos del ingenio).

  tablero/        código del tablero (tch-dashboard), sin sus datos
  tablones/       mapa de suertes de las dos plantas y su zona agroecológica (agrocontrol-campo)
  maestro.csv     copia del maestro oficial, respaldo si no hay internet (maestro-riopaila)
  inicial/        lo que siembra la carpeta de trabajo la primera vez: la tabla del satélite y la
                  última corrida del tablero (con su historial)
  publicacion.json  proyecto de Vercel y dirección de la app de Turnos (nada secreto)

Uso:  .venv-gee\\Scripts\\python.exe producto\\preparar_recursos.py
"""
import json
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
from tchmotor import rutas  # noqa: E402

DESTINO = AQUI / "recursos"
TABLERO = rutas.TABLERO_DATA.parent           # ~/tch-dashboard
MAESTRO = rutas.MAESTRO_LOCAL                 # ~/maestro-riopaila/maestro.csv
TURNOS_URL = "https://xqwwppgvncaogjxxzlhy.supabase.co"  # dirección pública de la app de Turnos
ALIAS = "estimador-tch.vercel.app"


def copiar(origen: Path, destino: Path):
    if not origen.exists():
        raise FileNotFoundError(f"Falta {origen}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if origen.is_dir():
        shutil.copytree(origen, destino, dirs_exist_ok=True)
    else:
        shutil.copy2(origen, destino)


def main():
    if DESTINO.exists():
        shutil.rmtree(DESTINO)
    for f in ("index.html", "styles.css", "app.js", "vercel.json", "logo-riopaila.png", "logo-castilla.png",
              "logo-riopaila-simbolo.png", "logo-castilla-simbolo.png"):
        copiar(TABLERO / f, DESTINO / "tablero" / f)
    for f in ("tablones_riopaila.geojson", "tablones_castilla.geojson", "maestro_suertes.json", "maestro_castilla.json"):
        copiar(rutas.TABLONES_DIR / f, DESTINO / "tablones" / f)
    copiar(MAESTRO, DESTINO / "maestro.csv")
    for f in ("mensual_riopaila.csv.gz", "mensual_castilla.csv.gz", "clima_mensual.csv.gz"):
        copiar(rutas.GEE_DIR / f, DESTINO / "inicial" / "satelite" / f)
    copiar(rutas.TABLERO_DATA, DESTINO / "inicial" / "tablero_data")
    vercel = json.loads((TABLERO / ".vercel" / "project.json").read_text(encoding="utf-8"))
    (DESTINO / "publicacion.json").write_text(json.dumps({
        "vercel_equipo": vercel["orgId"], "vercel_proyecto": vercel["projectId"],
        "vercel_nombre": vercel.get("projectName", "tch-dashboard"), "alias": ALIAS, "turnos_url": TURNOS_URL,
    }, indent=1), encoding="utf-8")
    meta = json.loads((rutas.TABLERO_DATA / "meta.json").read_text(encoding="utf-8"))
    n = sum(1 for _ in DESTINO.rglob("*") if _.is_file())
    mb = sum(p.stat().st_size for p in DESTINO.rglob("*") if p.is_file()) / 1e6
    print(f"recursos listos en {DESTINO}: {n} archivos · {mb:.1f} MB · corrida inicial {meta['fecha_corrida']}")


if __name__ == "__main__":
    main()
