"""Servidor local de la ventana: sirve la interfaz, el tablero (con los datos de la carpeta de trabajo) y una
API pequeña para el estado, la configuración y las tareas. Solo escucha en 127.0.0.1 y exige un token
por sesión, para que ninguna página web abierta en el navegador pueda disparar tareas.
"""
from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, estado, tareas

TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
TAREA_PROGRAMADA = "Estimador TCH - corrida del mes (app)"


class Estado:
    def __init__(self, token: str):
        self.token = token
        self.gestor = tareas.Gestor()
        self.latido = time.time() + 120  # margen para que abra la ventana
        self.servidor: ThreadingHTTPServer | None = None
        self.ventana = None  # proceso de Edge en modo aplicación, si se abrió así


def _dentro(base: Path, rel: str) -> Path | None:
    p = (base / rel).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError:
        return None
    return p


def _elegir(tipo: str, titulo: str) -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    raiz = tk.Tk()
    raiz.withdraw()
    raiz.attributes("-topmost", True)
    try:
        if tipo == "carpeta":
            r = filedialog.askdirectory(title=titulo, parent=raiz)
        else:
            r = filedialog.askopenfilename(title=titulo, parent=raiz, filetypes=[("Llave JSON", "*.json"), ("Todos", "*.*")])
    finally:
        raiz.destroy()
    return os.path.normpath(r) if r else None


def _programar(activar: bool) -> str:
    if not activar:
        r = subprocess.run(["schtasks", "/Delete", "/TN", TAREA_PROGRAMADA, "/F"], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "Corrida automática desactivada." if r.returncode == 0 else "No había corrida automática."
    if config.congelado():
        accion = f'"{tareas.ruta_python()}" --tarea motor'
    else:
        accion = f'"{tareas.ruta_python()}" -m app.principal --tarea motor'
    r = subprocess.run(["schtasks", "/Create", "/TN", TAREA_PROGRAMADA, "/SC", "MONTHLY", "/D", "2", "/ST", "07:00",
                        "/TR", accion, "/F"], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError("Windows no dejó programar la corrida: " + (r.stderr or r.stdout).strip())
    return "Listo: el motor correrá solo el día 2 de cada mes a las 7:00 (sin publicar)."


def _programada() -> bool:
    r = subprocess.run(["schtasks", "/Query", "/TN", TAREA_PROGRAMADA], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0


def crear(token: str, puerto: int = 0) -> Estado:
    est = Estado(token)

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *a):  # sin ruido en la consola
            pass

        # ---------------- utilidades
        def _json(self, obj, codigo=200):
            b = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _archivo(self, p: Path | None):
            if p is None or not p.is_file():
                self.send_error(404)
                return
            b = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TIPOS.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _autorizado(self) -> bool:
            if self.headers.get("X-Token") != est.token:
                self._json({"error": "Sesión inválida: cierra y vuelve a abrir el Estimador."}, 403)
                return False
            return True

        def _cuerpo(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

        # ---------------- GET
        def do_GET(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            ruta, q = urllib.parse.unquote(u.path), urllib.parse.parse_qs(u.query)
            if ruta == "/api/ping":
                return self._json({"ok": True, "app": "EstimadorTCH"})
            if ruta.startswith("/api/"):
                if not self._autorizado():
                    return None
                try:
                    if ruta == "/api/estado":
                        r = estado.calcular()
                        t = est.gestor.actual
                        r["tarea"] = est.gestor.publico(t, 10 ** 12) if t else None
                        r["hechas"] = est.gestor.hechas
                        r["programada"] = _programada()
                        return self._json(r)
                    if ruta == "/api/config":
                        return self._json(config.resumen(config.cargar()))
                    if ruta == "/api/tarea":
                        r = est.gestor.consultar(q.get("id", [""])[0], int(q.get("desde", ["0"])[0]))
                        return self._json(r or {"error": "La tarea ya no existe"}, 200 if r else 404)
                except Exception as e:  # noqa: BLE001
                    return self._json({"error": str(e)}, 500)
                return self._json({"error": "No existe"}, 404)
            if ruta in ("/", "/index.html"):
                return self._archivo(config.ui_dir() / "index.html")
            if ruta.startswith("/ui/"):
                return self._archivo(_dentro(config.ui_dir(), ruta[4:]))
            if ruta.startswith("/tablero"):
                rel = ruta[len("/tablero"):].lstrip("/") or "index.html"
                if rel.startswith("data/"):
                    return self._archivo(_dentro(config.tablero_data(config.cargar()), rel[5:]))
                return self._archivo(_dentro(config.recursos() / "tablero", rel))
            self.send_error(404)
            return None

        # ---------------- POST
        def do_POST(self):  # noqa: N802
            ruta = urllib.parse.urlparse(self.path).path
            if not self._autorizado():
                return None
            try:
                c = self._cuerpo()
                if ruta == "/api/latido":
                    est.latido = time.time()
                    return self._json({"ok": True})
                if ruta == "/api/config":
                    secretos = {k: c.pop(k) for k in list(c) if k in config.SECRETOS}
                    cfg = config.guardar(c)
                    if secretos:
                        config.guardar_llaves(secretos)
                    copiado = config.preparar_trabajo(cfg) if c.get("carpeta_trabajo") else []
                    return self._json({"ok": True, "copiado": len(copiado), "config": config.resumen(cfg)})
                if ruta == "/api/llave_gee":
                    p = Path(c["ruta"])
                    datos = json.loads(p.read_text(encoding="utf-8"))
                    if not datos.get("client_email") or not datos.get("private_key"):
                        raise ValueError("Ese archivo no es una llave de cuenta de servicio de Google")
                    config.guardar_llaves({"gee_llave_json": json.dumps(datos)})
                    return self._json({"ok": True, "cuenta": datos["client_email"], "proyecto": datos.get("project_id")})
                if ruta == "/api/tarea":
                    tipo = c.get("tipo")
                    args = []
                    if tipo == "cosechas_app":
                        args = ["--mes", c["mes"]] + (["--simular"] if c.get("simular") else [])
                    elif tipo == "cosechas_lista":
                        p = tareas.archivo_temporal(c.get("texto", ""), "lista_pegada.txt")
                        args = ["--lista", str(p)] + (["--simular"] if c.get("simular") else [])
                    elif tipo == "motor":
                        args = [] if c.get("satelite", True) else ["--sin-gee"]
                    elif tipo == "aforos":
                        args = ["--aplicar"] if c.get("aplicar") else []
                    return self._json(est.gestor.iniciar(tipo, args))
                if ruta == "/api/detener":
                    return self._json({"ok": est.gestor.detener()})
                if ruta == "/api/elegir":
                    return self._json({"ruta": _elegir(c.get("tipo", "carpeta"), c.get("titulo", "Elegir"))})
                if ruta == "/api/abrir":
                    cfg = config.cargar()
                    destino = {"trabajo": config.trabajo(cfg), "registros": config.registros(cfg),
                               "insumos": Path(cfg["carpeta_insumos"])}.get(c.get("que"))
                    if c.get("que") == "log" and c.get("ruta"):
                        destino = Path(c["ruta"])
                    if destino is None or not destino.exists():
                        raise FileNotFoundError("No existe esa carpeta todavía")
                    os.startfile(destino)  # noqa: S606 - abre la carpeta en el Explorador
                    return self._json({"ok": True})
                if ruta == "/api/programar":
                    return self._json({"ok": True, "mensaje": _programar(bool(c.get("activar")))})
            except Exception as e:  # noqa: BLE001 - el error va a la ventana, en palabras
                return self._json({"error": str(e)}, 400)
            return self._json({"error": "No existe"}, 404)

    est.servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    est.servidor.daemon_threads = True

    def vigilar():
        # Se cierra cuando la ventana ya no existe y no hay tarea corriendo. Mientras el proceso de Edge siga
        # vivo no se cierra: con la ventana minimizada el navegador espacia las señales hasta 1 por minuto.
        while True:
            time.sleep(5)
            if est.gestor.ocupado() or (est.ventana is not None and est.ventana.poll() is None):
                continue
            if time.time() - est.latido > 90:
                est.servidor.shutdown()
                return

    threading.Thread(target=vigilar, daemon=True).start()
    return est
