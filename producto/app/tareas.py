"""Las tareas del ciclo mensual.

Cada tarea corre en un proceso aparte (el mismo programa con `--tarea <tipo>`), así un error del motor
no tumba la ventana y la memoria se libera al terminar. El proceso hijo escribe su avance en un archivo
de registro dentro de la carpeta de trabajo; la ventana lo va leyendo.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import threading
import traceback
import uuid
from pathlib import Path

from . import config

TITULOS = {
    "cosechas_app": "Cargar cosechas de Riopaila (app de Turnos)",
    "cosechas_lista": "Cargar cosechas pegadas (Castilla)",
    "motor": "Correr el motor",
    "aforos": "Actualizar el modelo en los aforos",
    "publicar": "Publicar el tablero",
    "probar_gee": "Probar Earth Engine",
    "probar_turnos": "Probar la app de Turnos",
    "probar_vercel": "Probar la publicación",
}


# ---------------------------------------------------------------- lado de la ventana
class Gestor:
    """Lanza una tarea a la vez y deja leer su registro mientras corre."""

    def __init__(self):
        self.actual: dict | None = None
        self.hechas: list[dict] = []
        self._lock = threading.Lock()

    def ocupado(self) -> bool:
        return self.actual is not None and self.actual["proc"].poll() is None

    def iniciar(self, tipo: str, args: list[str]) -> dict:
        if tipo not in TITULOS:
            raise ValueError(f"Tarea desconocida: {tipo}")
        with self._lock:
            if self.ocupado():
                raise RuntimeError("Ya hay una tarea corriendo: espera a que termine.")
            cfg = config.cargar()
            carpeta = config.registros(cfg)
            try:
                carpeta.mkdir(parents=True, exist_ok=True)
            except OSError:
                carpeta = config.APP_DIR / "registros"
                carpeta.mkdir(parents=True, exist_ok=True)
            ahora = dt.datetime.now()
            log = carpeta / f"{ahora:%Y-%m-%d_%H%M%S}_{tipo}.log"
            if config.congelado():
                cmd = [sys.executable, "--tarea", tipo, "--log", str(log), *args]
            else:
                cmd = [sys.executable, "-m", "app.principal", "--tarea", tipo, "--log", str(log), *args]
            proc = subprocess.Popen(cmd, cwd=str(config.base()), env=config.entorno(cfg),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.actual = {"id": uuid.uuid4().hex[:10], "tipo": tipo, "titulo": TITULOS[tipo], "args": args,
                           "inicio": ahora.isoformat(timespec="seconds"), "log": str(log), "proc": proc}
            return self.publico(self.actual)

    def publico(self, t: dict, desde: int = 0) -> dict:
        codigo = t["proc"].poll()
        texto, fin = "", desde
        try:
            with open(t["log"], "rb") as f:
                f.seek(desde)
                datos = f.read()
                fin = desde + len(datos)
                texto = datos.decode("utf-8", errors="replace")
        except FileNotFoundError:
            pass
        return {"id": t["id"], "tipo": t["tipo"], "titulo": t["titulo"], "inicio": t["inicio"],
                "estado": "corriendo" if codigo is None else ("ok" if codigo == 0 else "error"),
                "codigo": codigo, "texto": texto, "desde": fin, "log": t["log"]}

    def consultar(self, ident: str, desde: int = 0) -> dict | None:
        t = self.actual
        if t is None or t["id"] != ident:
            return None
        r = self.publico(t, desde)
        if r["estado"] != "corriendo" and not any(h["id"] == t["id"] for h in self.hechas):
            self.hechas.insert(0, {k: r[k] for k in ("id", "tipo", "titulo", "inicio", "estado", "log")})
            del self.hechas[20:]
        return r

    def detener(self) -> bool:
        if self.ocupado():
            self.actual["proc"].terminate()
            return True
        return False


# ---------------------------------------------------------------- lado del proceso hijo
def _scripts():
    """En el código fuente los programas viven en tch-motor/scripts; en el instalado van empaquetados."""
    if not config.congelado():
        raiz = config.base().parent
        for p in (raiz, raiz / "scripts"):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))


def _correr_script(modulo: str, argv: list[str]):
    _scripts()
    m = __import__(modulo)
    sys.argv = [f"{modulo}.py", *argv]
    m.main()


def ejecutar(tipo: str, args: list[str], log: str | None) -> int:
    """Corre una tarea en este proceso, escribiendo todo lo que imprime en `log`."""
    salida = open(log, "a", encoding="utf-8", buffering=1) if log else sys.__stdout__
    sys.stdout = sys.stderr = salida
    print(f"{TITULOS.get(tipo, tipo)} · {dt.datetime.now():%Y-%m-%d %H:%M}", flush=True)
    try:
        if tipo == "cosechas_app":
            _correr_script("cosechas_desde_app", args)
        elif tipo == "cosechas_lista":
            _correr_script("cosechas_desde_app", args)
        elif tipo == "motor":
            _correr_script("mensual", args)
        elif tipo == "aforos":
            _correr_script("modelo_en_aforos", args)
        elif tipo == "publicar":
            from . import publicar
            publicar.publicar(config.cargar(), config.llaves())
        elif tipo == "probar_gee":
            _scripts()
            import ee
            from tchmotor import gee
            proyecto, quien = gee.iniciar()
            ee.Number(1).add(1).getInfo()
            print(f"Earth Engine responde: proyecto {proyecto}, cuenta {quien}.")
        elif tipo == "probar_turnos":
            _scripts()
            from tchmotor import turnos
            print(f"La app de Turnos responde: {len(turnos.aforos())} aforos registrados.")
        elif tipo == "probar_vercel":
            from . import publicar
            publicar.probar(config.cargar(), config.llaves())
        else:
            raise ValueError(f"Tarea desconocida: {tipo}")
    except SystemExit as e:  # argparse y algunos programas terminan con sys.exit
        codigo = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        print("\n✔ Listo." if codigo == 0 else f"\n✖ Terminó con error ({e.code}).", flush=True)
        return codigo
    except Exception as e:  # noqa: BLE001 - todo error va al registro para que se pueda leer en la ventana
        print(f"\n✖ Error: {e}", flush=True)
        traceback.print_exc(file=salida)
        return 1
    print("\n✔ Listo.", flush=True)
    return 0


def archivo_temporal(texto: str, nombre: str) -> Path:
    """Guarda texto pegado en la ventana (p. ej. la lista de Castilla) para pasárselo a una tarea."""
    d = config.APP_DIR / "temporal"
    d.mkdir(parents=True, exist_ok=True)
    p = d / nombre
    p.write_text(texto, encoding="utf-8")
    return p


def ruta_python() -> str:
    return os.path.abspath(sys.executable)
