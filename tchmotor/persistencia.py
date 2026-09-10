"""Persistencia en el Supabase de Rio Map (tablas tch_*), vía PostgREST.

Lee las tablas de referencia (var_map, aforo sintético) y escribe los estimados
del job. La escritura usa la **service_role key** (secreto de servidor); las
credenciales salen del entorno (`TCH_SUPABASE_URL`, `TCH_SUPABASE_KEY`), nunca
hardcodeadas. El transporte HTTP es inyectable para poder testear sin red.
"""
from __future__ import annotations
import json
import os
import urllib.request
import urllib.parse


def _http(method: str, url: str, headers: dict, body: bytes | None):
    """Transporte por defecto (urllib). Devuelve (status, texto)."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read().decode()


class Supabase:
    """Cliente mínimo de PostgREST para las tablas del producto."""

    def __init__(self, url: str | None = None, key: str | None = None, http=_http):
        self.url = (url or os.environ.get("TCH_SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("TCH_SUPABASE_KEY", "")
        self._http = http
        if not self.url or not self.key:
            raise ValueError(
                "faltan TCH_SUPABASE_URL / TCH_SUPABASE_KEY (o pásalas al constructor)"
            )

    def _headers(self, extra: dict | None = None) -> dict:
        h = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def leer(self, tabla: str, select: str = "*", **filtros) -> list[dict]:
        """GET de una tabla con `select` y filtros PostgREST (`col=eq.valor`)."""
        params = {"select": select, **filtros}
        url = f"{self.url}/rest/v1/{tabla}?{urllib.parse.urlencode(params)}"
        status, txt = self._http("GET", url, self._headers(), None)
        if status >= 300:
            raise RuntimeError(f"leer {tabla}: {status} {txt[:200]}")
        return json.loads(txt)

    def upsert(self, tabla: str, filas: list[dict], on_conflict: str) -> int:
        """Inserta/actualiza filas (merge por `on_conflict`). Devuelve el nº."""
        if not filas:
            return 0
        url = f"{self.url}/rest/v1/{tabla}?on_conflict={on_conflict}"
        headers = self._headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
        status, txt = self._http("POST", url, headers, json.dumps(filas).encode())
        if status >= 300:
            raise RuntimeError(f"upsert {tabla}: {status} {txt[:200]}")
        return len(filas)

    # --- conveniencias del dominio ---
    def cargar_var_map(self) -> dict[str, str]:
        return {r["codigo"]: r["nombre"] for r in self.leer("tch_var_map")}

    def cargar_aforo_sintetico(self) -> list[dict]:
        return self.leer("tch_aforo_sintetico")

    def guardar_aforo_sintetico(self, filas: list[dict]) -> int:
        return self.upsert("tch_aforo_sintetico", filas, on_conflict="variedad,soca")

    def guardar_estimados(self, filas: list[dict]) -> int:
        return self.upsert("tch_estimado", filas, on_conflict="sec_ste,fecha_corrida")

    def cargar_estimados(self, fecha_corrida: str | None = None) -> list[dict]:
        filtros = {"fecha_corrida": f"eq.{fecha_corrida}"} if fecha_corrida else {}
        return self.leer("tch_estimado", **filtros)

    # --- P5: cortes reales y factor aprendido ---
    def cargar_reales(self, campana: str | None = None) -> list[dict]:
        filtros = {"campana": f"eq.{campana}"} if campana else {}
        return self.leer("tch_real", **filtros)

    def guardar_reales(self, filas: list[dict]) -> int:
        return self.upsert("tch_real", filas, on_conflict="sec_ste,campana")

    def guardar_factores(self, filas: list[dict]) -> int:
        return self.upsert("tch_factor", filas, on_conflict="planta,campana")

    def cargar_factores(self) -> dict[str, float]:
        """{planta: factor} vigente = el de la campaña más reciente por planta."""
        filas = self.leer("tch_factor", select="planta,campana,factor",
                          order="campana.desc")
        out: dict[str, float] = {}
        for f in filas:
            out.setdefault(f["planta"], float(f["factor"]))
        return out
