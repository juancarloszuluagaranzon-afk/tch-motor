"""Lectura de aforos EN VIVO desde el Supabase de Turnos & Jornales.

Los técnicos capturan el aforo físico en Turnos & Jornales (tabla
`aforo_records`, con `tch_pesos` ya calculado). Aquí se trae, por suerte, el
aforo más reciente ANTERIOR a la fecha de estimación (disciplina temporal: no
usar un aforo posterior, sería mirar el futuro). Turnos es OTRO proyecto
Supabase, así que se pasa su propio cliente.
"""
from __future__ import annotations


def aforos_vigentes(sb_turnos, hasta_fecha: str) -> dict[str, float]:
    """{sec_ste: tch_pesos} del aforo más reciente de cada suerte antes de la fecha."""
    filas = sb_turnos.leer(
        "aforo_records",
        select="suerte,date,tch_pesos",
        **{
            "date": f"lt.{hasta_fecha}",       # solo aforos anteriores a la corrida
            "tch_pesos": "not.is.null",
            "order": "date.desc",
        },
    )
    vigente: dict[str, float] = {}
    for f in filas:  # ya vienen ordenados por fecha desc → el primero es el vigente
        s = (f.get("suerte") or "").strip()
        if s and s not in vigente and f.get("tch_pesos") is not None:
            vigente[s] = float(f["tch_pesos"])
    return vigente
