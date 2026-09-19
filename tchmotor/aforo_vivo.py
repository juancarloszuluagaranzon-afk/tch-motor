"""Lectura de aforos EN VIVO desde el Supabase de Turnos & Jornales.

Los técnicos capturan el aforo físico en Turnos & Jornales (tabla
`aforo_records`). Aquí se trae, por suerte, el aforo más reciente ANTERIOR a la
fecha de estimación (disciplina temporal: no usar un aforo posterior, sería
mirar el futuro). Turnos es OTRO proyecto Supabase, así que se pasa su propio
cliente.

El valor devuelto es el PROMEDIO de los tres métodos del aforo (diámetro,
día-a-12-meses, pesos): validado como el mejor (MAPE 14,4 % vs 19,4 % de 'pesos'
solo). Se prefiere una columna de promedio ya calculada si existe; si no, se
promedian los métodos presentes; como último recurso se usa 'pesos'. La lectura
es agnóstica al esquema (select *) para tolerar cómo se cargue el libro de aforos.
"""
from __future__ import annotations

# nombres posibles de columnas segun como se cargue el libro de aforos
_PROMEDIO = ("tch_promedio", "promedio", "tch_prom")
_METODOS = ("tch_diametro", "tch_dia12m", "tch_dia_12_meses", "tch_12m", "tch_pesos")


def _valor_aforo(f: dict) -> float | None:
    """Promedio de los 3 métodos: columna de promedio si existe, si no el promedio
    de los métodos presentes, si no 'pesos'. None si no hay ningún dato."""
    for k in _PROMEDIO:
        v = f.get(k)
        if v is not None:
            return float(v)
    vals = [float(f[k]) for k in _METODOS if f.get(k) is not None]
    return sum(vals) / len(vals) if vals else None


def aforos_vigentes(sb_turnos, hasta_fecha: str) -> dict[str, float]:
    """{sec_ste: tch_aforo_promedio} del aforo más reciente de cada suerte antes
    de `hasta_fecha`."""
    filas = sb_turnos.leer(
        "aforo_records",
        select="*",
        **{
            "date": f"lt.{hasta_fecha}",   # solo aforos anteriores a la corrida
            "order": "date.desc",
        },
    )
    vigente: dict[str, float] = {}
    for f in filas:  # ya vienen ordenados por fecha desc → el primero es el vigente
        s = (f.get("suerte") or f.get("sec_ste") or "").strip()
        if not s or s in vigente:
            continue
        v = _valor_aforo(f)
        if v is not None:
            vigente[s] = v
    return vigente
