"""P5 — auto-recalibración desde cosechas cerradas.

Empareja los cortes reales ya cosechados (`tch_real`) con lo que el motor estimó
(`tch_estimado`), deshace la recalibración vieja para recuperar el estimado CRUDO,
y deriva por planta el factor nuevo k = Σ(real·área)/Σ(crudo·área) más el
diagnóstico (sesgo del crudo, MAPE residual del estimado reportado). Escribe
`tch_factor`, que el job mensual lee para reemplazar el 0.981/0.914 fijo.

Solo usa filas en modo 'motor': ahí `tch_estimado = crudo × factor_recal`, así que
el crudo se recupera exacto. Las de 'fusion' ya llevan el aforo corrigiéndolas y no
sirven para aislar el sesgo del motor.
"""
from __future__ import annotations

from .recalibracion import diagnosticos

VERSION = "v0.1"


class JobRecalibracion:
    def __init__(self, supabase):
        self.sb = supabase

    def emparejar(self, campana: str, fecha_corrida: str | None = None) -> list[dict]:
        """Registros {planta, crudo, aplicado, real, area} de cortes cerrados que
        casan con un estimado en modo motor."""
        reales = {r["sec_ste"]: r for r in self.sb.cargar_reales(campana)}
        registros = []
        for e in self.sb.cargar_estimados(fecha_corrida):
            if e.get("modo") != "motor":
                continue
            r = reales.get(e["sec_ste"])
            if not r:
                continue
            # emparejar solo la MISMA soca: el estimado de una suerte ya cortada es
            # la soca nueva (joven); su real es la soca vieja. Cruzarlos contamina el
            # factor (ver dashboard realDe). Si ambos traen soca y difieren, se salta.
            e_soca, r_corte = e.get("soca"), r.get("corte")
            if e_soca is not None and r_corte is not None and int(e_soca) != int(r_corte):
                continue
            k_old = e.get("factor_recal") or 1.0
            aplicado = e.get("tch_estimado")
            real = r.get("tch_real")
            area = e.get("area_ha") or r.get("area_ha")
            if not aplicado or not real or not area or k_old <= 0:
                continue
            registros.append({
                "planta": e.get("planta") or r.get("planta"),
                "crudo": float(aplicado) / k_old,
                "aplicado": float(aplicado),
                "real": float(real),
                "area": float(area),
            })
        return registros

    def calcular(self, campana: str, fecha_corrida: str | None = None,
                 vigente_desde: str | None = None) -> list[dict]:
        """Filas de `tch_factor` (una por planta). No escribe."""
        registros = self.emparejar(campana, fecha_corrida)
        plantas = sorted({r["planta"] for r in registros if r["planta"]})
        filas = []
        for planta in plantas:
            rs = [r for r in registros if r["planta"] == planta]
            crudo = diagnosticos([r["crudo"] for r in rs], [r["real"] for r in rs],
                                 [r["area"] for r in rs])
            aplicado = diagnosticos([r["aplicado"] for r in rs], [r["real"] for r in rs],
                                    [r["area"] for r in rs])
            filas.append({
                "planta": planta,
                "campana": campana,
                "factor": round(crudo["factor"], 4),
                "n_suertes": crudo["n"],
                "area_ha": crudo["area_ha"],
                "tch_real_agg": crudo["tch_real_agg"],
                "tch_est_agg": crudo["tch_est_agg"],
                "sesgo_pct": crudo["sesgo_pct"],   # del crudo → cuánto corre caliente el motor
                "mape": aplicado["mape"],           # del reportado → calidad residual
                "vigente_desde": vigente_desde,
                "modelo_version": VERSION,
            })
        return filas

    def correr(self, campana: str, fecha_corrida: str | None = None,
               vigente_desde: str | None = None):
        """Calcula y escribe en tch_factor. Devuelve (filas, n)."""
        filas = self.calcular(campana, fecha_corrida, vigente_desde)
        n = self.sb.guardar_factores(filas)
        return filas, n
