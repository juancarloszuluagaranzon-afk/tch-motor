"""Publica el tablero en Vercel por su API (sin Git ni la línea de comandos de Vercel).

Arma el sitio con el código del tablero que trae el instalador y los datos de la carpeta de trabajo,
sube solo los archivos que Vercel no tenga (se identifican por su SHA-1), crea un despliegue de producción
y le pone el alias público (estimador-tch.vercel.app). Al final comprueba que el sitio publicado ya muestra
la corrida nueva.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config

API = "https://api.vercel.com"


def _pedir(metodo: str, ruta: str, token: str, equipo: str, cuerpo=None, datos: bytes | None = None,
           cabeceras: dict | None = None, intentos: int = 3):
    q = f"{'&' if '?' in ruta else '?'}teamId={urllib.parse.quote(equipo)}" if equipo else ""
    h = {"Authorization": f"Bearer {token}", **(cabeceras or {})}
    if cuerpo is not None:
        datos, h["Content-Type"] = json.dumps(cuerpo).encode("utf-8"), "application/json"
    for i in range(intentos):
        req = urllib.request.Request(API + ruta + q, data=datos, method=metodo, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                txt = r.read().decode("utf-8")
                return r.status, (json.loads(txt) if txt.strip() else {})
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", errors="replace")
            try:
                cuerpo_err = json.loads(txt)
            except ValueError:
                cuerpo_err = {"error": {"message": txt[:300]}}
            if e.code >= 500 and i < intentos - 1:
                time.sleep(2 * (i + 1))
                continue
            return e.code, cuerpo_err
        except urllib.error.URLError:
            if i < intentos - 1:
                time.sleep(2 * (i + 1))
                continue
            raise
    raise RuntimeError("Vercel no respondió")


def archivos_del_sitio(cfg: dict) -> dict[str, Path]:
    """{ruta publicada: archivo local}: el código del tablero empaquetado + data/ de la carpeta de trabajo."""
    codigo = config.recursos() / "tablero"
    sitio = {p.relative_to(codigo).as_posix(): p for p in codigo.rglob("*") if p.is_file()}
    datos = config.tablero_data(cfg)
    if not (datos / "estimados.json").exists():
        raise FileNotFoundError(f"No hay corrida en {datos}: corre el motor antes de publicar")
    sitio.update({"data/" + p.relative_to(datos).as_posix(): p for p in datos.rglob("*") if p.is_file()})
    return sitio


def _faltan_datos(cfg: dict, llaves: dict):
    faltan = [n for n, v in (("token de Vercel", llaves.get("vercel_token")), ("proyecto de Vercel", cfg.get("vercel_proyecto")),
                             ("alias del tablero", cfg.get("alias"))) if not v]
    if faltan:
        raise RuntimeError("Falta configurar: " + ", ".join(faltan))


def probar(cfg: dict, llaves: dict) -> None:
    _faltan_datos(cfg, llaves)
    st, r = _pedir("GET", f"/v9/projects/{urllib.parse.quote(cfg['vercel_proyecto'])}", llaves["vercel_token"],
                   cfg.get("vercel_equipo", ""))
    if st != 200:
        raise RuntimeError(f"Vercel no dejó leer el proyecto ({st}): {r.get('error', {}).get('message', r)}")
    print(f"Vercel responde: proyecto «{r.get('name')}». Se publicará en https://{cfg['alias']}")


def publicar(cfg: dict, llaves: dict) -> str:
    _faltan_datos(cfg, llaves)
    token, equipo = llaves["vercel_token"], cfg.get("vercel_equipo", "")
    sitio = archivos_del_sitio(cfg)
    meta = json.loads((config.tablero_data(cfg) / "meta.json").read_text(encoding="utf-8"))
    print(f"Corrida del {meta['fecha_corrida']} · {len(sitio)} archivos", flush=True)

    contenido, lista = {}, []
    for ruta, p in sorted(sitio.items()):
        b = p.read_bytes()
        sha = hashlib.sha1(b).hexdigest()
        contenido[sha] = b
        lista.append({"file": ruta, "sha": sha, "size": len(b)})

    def subir(sha: str):
        b = contenido[sha]
        st, r = _pedir("POST", "/v2/files", token, equipo, datos=b,
                       cabeceras={"Content-Type": "application/octet-stream", "x-vercel-digest": sha,
                                  "Content-Length": str(len(b))})
        if st != 200:
            raise RuntimeError(f"No se pudo subir un archivo ({st}): {r.get('error', {}).get('message', r)}")

    cuerpo = {"name": cfg.get("vercel_nombre") or "tch-dashboard", "project": cfg["vercel_proyecto"],
              "target": "production", "files": lista, "projectSettings": {"framework": None}}
    ruta_crear = "/v13/deployments?skipAutoDetectionConfirmation=1"
    st, r = _pedir("POST", ruta_crear, token, equipo, cuerpo=cuerpo)
    if st == 400 and r.get("error", {}).get("code") == "missing_files":
        faltan = r["error"].get("missing") or list(contenido)
        print(f"Subiendo {len(faltan)} archivos nuevos o cambiados…", flush=True)
        hechos = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            for _ in ex.map(subir, faltan):
                hechos += 1
                if hechos % 200 == 0:
                    print(f"  {hechos} de {len(faltan)}", flush=True)
        st, r = _pedir("POST", ruta_crear, token, equipo, cuerpo=cuerpo)
    if st not in (200, 201):
        raise RuntimeError(f"Vercel no aceptó el despliegue ({st}): {r.get('error', {}).get('message', r)}")
    ident, url = r["id"], r.get("url")
    print(f"Despliegue creado ({url}). Esperando a que quede listo…", flush=True)
    for _ in range(120):
        st, r = _pedir("GET", f"/v13/deployments/{ident}", token, equipo)
        estado = r.get("readyState") or r.get("status")
        if estado == "READY":
            break
        if estado in ("ERROR", "CANCELED"):
            raise RuntimeError(f"El despliegue terminó en {estado}: {r.get('errorMessage', '')}")
        time.sleep(5)
    else:
        raise RuntimeError("El despliegue no quedó listo en 10 minutos; revísalo en Vercel")
    st, r = _pedir("POST", f"/v2/deployments/{ident}/aliases", token, equipo, cuerpo={"alias": cfg["alias"]})
    if st not in (200, 201):
        raise RuntimeError(f"Quedó publicado en https://{url} pero no se pudo mover el alias ({st}): "
                           f"{r.get('error', {}).get('message', r)}")
    publico = f"https://{cfg['alias']}"
    for _ in range(12):  # el alias tarda unos segundos en apuntar al despliegue nuevo
        try:
            with urllib.request.urlopen(f"{publico}/data/meta.json?v={int(time.time())}", timeout=20) as resp:
                if json.loads(resp.read().decode("utf-8")).get("fecha_corrida") == meta["fecha_corrida"]:
                    print(f"Publicado: {publico} ya muestra la corrida del {meta['fecha_corrida']}.", flush=True)
                    return publico
        except (urllib.error.URLError, ValueError):
            pass
        time.sleep(5)
    print(f"Publicado en {publico}; todavía no muestra la corrida nueva, revísalo en un minuto.", flush=True)
    return publico


def publicado(cfg: dict) -> dict:
    """Qué corrida muestra hoy el tablero público (para el panel de estado)."""
    try:
        with urllib.request.urlopen(f"https://{cfg['alias']}/data/meta.json?v={int(time.time())}", timeout=6) as r:
            m = json.loads(r.read().decode("utf-8"))
        return {"ok": True, "fecha": m.get("fecha_corrida"), "version": m.get("modelo_version")}
    except Exception as e:  # noqa: BLE001 - sin internet el panel lo dice y sigue
        return {"ok": False, "error": str(e)[:120]}
