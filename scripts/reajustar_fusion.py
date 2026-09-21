# -*- coding: utf-8 -*-
"""Re-ajusta los coeficientes de la fusión (motor+aforo) con las cosechas cerradas
de la campaña — el análogo de la recalibración del factor, para la fusión.

Cómo funciona:
  - Toma las suertes YA COSECHADAS (tch_real, fuente cosecha_2026) que casan con un
    estimado en modo 'fusion' de la corrida vigente y MISMA soca (soca-limpio).
  - Recupera el `motor_recal` que entró a la fusión invirtiendo la fórmula
    (motor_recal = (aplicado − b·aforo − c)/a); no depende de k_old.
  - Lo re-escala a la base del factor del motor VIGENTE (tch_factor), que es lo que
    la próxima corrida le pasará a `combinar`, y re-ajusta a,b,c con `Fusion.ajustar`.
  - Imprime los coeficientes y el MAPE/sesgo antes y después. NO escribe código:
    los coeficientes se copian a mano a tchmotor/fusion.py (cambio revisable).

Uso: python scripts/reajustar_fusion.py [--mes 2026-09]
"""
import argparse, json, os, sys, urllib.request
sys.path.insert(0, r"C:\Users\Agr349\tch-motor")
sys.path.insert(0, r"C:\Users\Agr349\tch-motor\scripts")
import correr_estimados as ce
from tchmotor import Supabase
from tchmotor.fusion import Fusion

AGRO = r"C:\Users\Agr349\agrocontrol-campo\.env.local"
TURN = r"C:\Users\Agr349\turnos-jornales\.env.local"
K_OLD = 0.981  # factor de la corrida 2026-09-09 (fijo; el aprendido se escribió después)
# Coeficientes de fusión CON LOS QUE SE CALCULÓ la corrida vigente (2026-09-09).
# La inversión motor_recal = (aplicado − b·aforo − c)/a debe usar ESTOS, no las
# constantes actuales de fusion.py: si se re-ajustó fusion.py y se re-corre este
# script sobre la MISMA corrida (aún calculada con los viejos), usar los nuevos
# invertiría mal y daría un segundo ajuste espurio. Cuando exista una corrida nueva
# calculada con otros coeficientes, actualizar estos (o pasarlos por --coef-*).
COEF_CORRIDA = (0.5208, 0.3456, 10.2058)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def turnos_get(tabla):
    url = ce._env(TURN, "NEXT_PUBLIC_SUPABASE_URL").rstrip("/")
    key = ce._env(TURN, "SUPABASE_SERVICE_ROLE_KEY")
    filas, off = [], 0
    while True:
        u = f"{url}/rest/v1/{tabla}?select=*&limit=1000&offset={off}"
        req = urllib.request.Request(u, headers={"apikey": key, "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            lote = json.loads(r.read().decode())
        filas.extend(lote)
        if len(lote) < 1000:
            break
        off += 1000
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", default="2026-09")
    ap.add_argument("--coef-motor", type=float, default=COEF_CORRIDA[0], help="coef. motor CON EL QUE SE CORRIÓ la corrida")
    ap.add_argument("--coef-aforo", type=float, default=COEF_CORRIDA[1])
    ap.add_argument("--intercepto", type=float, default=COEF_CORRIDA[2])
    args = ap.parse_args()
    cm_cor, ca_cor, ic_cor = args.coef_motor, args.coef_aforo, args.intercepto

    os.environ.setdefault("TCH_SUPABASE_URL", ce._env(AGRO, "NEXT_PUBLIC_SUPABASE_URL"))
    os.environ.setdefault("TCH_SUPABASE_KEY", ce._env(TURN, "RIOMAP_SERVICE_ROLE_KEY"))
    sb = Supabase()

    kfac = {f["planta"]: float(f["factor"]) for f in
            sb.leer("tch_factor", select="planta,campana,factor", order="campana.desc")}
    k_next = kfac.get("riopaila", K_OLD)
    corrida = max(e["fecha_corrida"] for e in sb.cargar_estimados())
    est = {e["sec_ste"]: e for e in sb.cargar_estimados(corrida) if e["planta"] == "riopaila"}

    af = {}
    for a in sb.leer("tch_aforo_vivo"):
        sec = a.get("suerte") or a.get("sec_ste")
        ms = [m for m in (num(a.get("tch_diametro")), num(a.get("tch_pesos"))) if m is not None]
        if not sec or not ms:
            continue
        v = sum(ms) / len(ms)
        prev = af.get(sec)
        if prev is None or (a.get("date") or "") > prev[1]:
            af[sec] = (v, a.get("date") or "")

    reales = {r["sec_ste"]: r for r in sb.cargar_reales("2026") if r.get("fuente") == "cosecha_2026"}

    M, A, R, aplic = [], [], [], []
    for sec, e in est.items():
        if e.get("modo") != "fusion":
            continue
        r = reales.get(sec)
        if not r:
            continue
        if e.get("soca") is not None and r.get("corte") is not None and int(e["soca"]) != int(r["corte"]):
            continue
        real = num(r.get("tch_real"))
        apl = num(e.get("tch_estimado"))
        a0 = af.get(sec)
        if real is None or apl is None or a0 is None:
            continue
        mr_old = (apl - ca_cor * a0[0] - ic_cor) / cm_cor
        M.append(mr_old * (k_next / K_OLD))  # base = factor del motor vigente
        A.append(a0[0]); R.append(real); aplic.append(apl)

    if not M:
        print("sin datos soca-limpio de fusión para el mes; nada que ajustar.")
        return
    mape_old = 100 * sum(abs(p - r) / r for p, r in zip(aplic, R)) / len(R)
    sesgo_old = 100 * (sum(aplic) / sum(R) - 1)
    fnew = Fusion.ajustar(M, A, R)
    pred = [fnew.combinar(m, a) for m, a in zip(M, A)]
    mape_new = 100 * sum(abs(p - r) / r for p, r in zip(pred, R)) / len(R)
    sesgo_new = 100 * (sum(pred) / sum(R) - 1)

    print(f"corrida {corrida} | k_next(tch_factor)={k_next} | n={len(M)} (fusión soca-limpio, {args.mes})")
    print(f"CORRIDA  a={cm_cor} b={ca_cor} c={ic_cor}  MAPE {mape_old:.1f}% sesgo {sesgo_old:+.1f}% (aplicado guardado vs real)")
    print(f"NUEVOS   a={fnew.coef_motor:.4f} b={fnew.coef_aforo:.4f} c={fnew.intercepto:.4f}  MAPE {mape_new:.1f}% sesgo {sesgo_new:+.1f}%")
    print("\nCopia a tchmotor/fusion.py:")
    print(f"  COEF_MOTOR = {fnew.coef_motor:.4f}")
    print(f"  COEF_AFORO = {fnew.coef_aforo:.4f}")
    print(f"  INTERCEPTO = {fnew.intercepto:.4f}")


if __name__ == "__main__":
    main()
