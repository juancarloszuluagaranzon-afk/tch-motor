"""Entrada del Estimador TCH.

  EstimadorTCH.exe                    abre la ventana (o trae al frente la que ya esté abierta)
  EstimadorTCH.exe --tarea <tipo> …   corre una tarea sin ventana (así las lanza la ventana y la corrida programada)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import secrets
import shutil
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path


def _tarea(argv: list[str]) -> int:
    from . import config, tareas

    tipo = argv[argv.index("--tarea") + 1]
    resto = [a for i, a in enumerate(argv) if i not in (argv.index("--tarea"), argv.index("--tarea") + 1)]
    log = None
    if "--log" in resto:
        i = resto.index("--log")
        log = resto[i + 1]
        resto = resto[:i] + resto[i + 2:]
    else:  # corrida programada: el entorno y el registro los arma aquí
        cfg = config.cargar()
        os.environ.update(config.entorno(cfg))
        carpeta = config.registros(cfg)
        carpeta.mkdir(parents=True, exist_ok=True)
        log = str(carpeta / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{tipo}_programada.log")
    return tareas.ejecutar(tipo, resto, log)


def _edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return shutil.which("msedge")


def _abrir_ventana(url: str, perfil: Path):
    """Abre la interfaz en Edge como ventana de aplicación (perfil propio, así su proceso dura lo que dura
    la ventana). Sin Edge, en el navegador predeterminado. Devuelve el proceso de Edge o None."""
    edge = _edge()
    if edge:
        return subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={perfil}", "--no-first-run",
                                 "--no-default-browser-check", "--disable-background-mode", "--window-size=1320,900"],
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    webbrowser.open(url)
    return None


def _ya_abierta(archivo: Path) -> str | None:
    """Si otra copia del Estimador está corriendo, devuelve su dirección."""
    try:
        d = json.loads(archivo.read_text(encoding="utf-8"))
        with urllib.request.urlopen(f"http://127.0.0.1:{d['puerto']}/api/ping", timeout=2) as r:
            if json.loads(r.read().decode("utf-8")).get("app") == "EstimadorTCH":
                return f"http://127.0.0.1:{d['puerto']}/?t={d['token']}"
    except Exception:  # noqa: BLE001 - no hay otra copia, o quedó un archivo viejo
        return None
    return None


def _opcion(nombre: str, defecto=None):
    if nombre in sys.argv and sys.argv.index(nombre) + 1 < len(sys.argv):
        return sys.argv[sys.argv.index(nombre) + 1]
    return defecto


def main() -> int:
    datos = _opcion("--datos")  # para pruebas: otra carpeta de configuración en vez de %APPDATA%\EstimadorTCH
    if datos:
        os.environ["ESTIMADORTCH_DATOS"] = datos
    if "--tarea" in sys.argv:
        return _tarea(sys.argv[1:])
    from . import config, servidor

    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    archivo = config.APP_DIR / "sesion.json"
    perfil = config.APP_DIR / "ventana"
    url = _ya_abierta(archivo)
    if url:
        _abrir_ventana(url, perfil)
        return 0
    token = _opcion("--token") or secrets.token_urlsafe(24)
    est = servidor.crear(token, int(_opcion("--puerto", 0)))
    puerto = est.servidor.server_address[1]
    archivo.write_text(json.dumps({"puerto": puerto, "token": token, "pid": os.getpid()}), encoding="utf-8")
    url = f"http://127.0.0.1:{puerto}/?t={token}"
    if "--sin-ventana" not in sys.argv:
        est.ventana = _abrir_ventana(url, perfil)
    else:
        print(url, flush=True)
    try:
        est.servidor.serve_forever()
    finally:
        try:
            archivo.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
