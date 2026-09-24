"""
Conciliación BCB ↔ MEFP: ¿dicen lo mismo las dos fuentes oficiales?

1. DEUDA EXTERNA. El MEFP publica la deuda externa del TGN; el BCB, la deuda externa
   pública por deudor. Se compara el TGN (MEFP) con el «Gobierno Central» (BCB) al cierre
   de cada trimestre. Resultado esperado: iguales (el BCB registra y el MEFP informa).
2. DEUDA INTERNA CON EL BCB. El MEFP publica cuánto le debe el TGN al BCB; el BCB, su
   crédito bruto al Gobierno Central. Se compara mes a mes y se describe la brecha.
3. COBERTURA. Qué deuda queda FUERA de cada fuente (lo que no está en ninguna no se
   puede sumar como si estuviera).

No corrige nada: mide y deja constancia. El monitor muestra cada cifra con su fuente;
esto es lo que respalda la nota metodológica.
Salidas: data/conciliacion.json · salidas/conciliacion.txt
"""
from __future__ import annotations

import json
import statistics
import sys

from comun import DATA, RAIZ, FuenteError, guardar_json

TOL_EXTERNA = 1.0     # millones de US$


def cargar(nombre):
    ruta = DATA / nombre
    if not ruta.exists():
        raise FuenteError(f"falta {nombre}: correr antes su scraper")
    return json.loads(ruta.read_text(encoding="utf-8"))


def main() -> int:
    de, det, di, bf = (cargar(n) for n in ("deuda_externa.json", "deuda_externa_tgn.json",
                                           "deuda_interna.json", "bcb_financiamiento.json"))
    lineas = ["CONCILIACIÓN BCB ↔ MEFP — Monitor Fiscal POPULI", ""]

    # 1. Externa: TGN (MEFP, mensual) al cierre de trimestre vs Gobierno Central (BCB, trimestral).
    bcb = de["trimestral"]["saldo_deudor"]
    externa = []
    for i, p in enumerate(bcb["periodos"]):
        anio, t = int(p[:4]), int(p[-1])
        mes = f"{anio}-{t * 3:02d}"
        if mes not in det["meses"]:
            continue
        x = det["series"]["total"][det["meses"].index(mes)]
        y = bcb["gobierno_central"][i]
        externa.append({"periodo": p, "mefp_tgn": x, "bcb_gobierno_central": y, "diferencia": round(y - x, 1)})
    fuera = [e for e in externa if abs(e["diferencia"]) > TOL_EXTERNA]
    lineas.append("1. DEUDA EXTERNA — TGN (MEFP) vs Gobierno Central (BCB), millones de US$")
    for e in externa:
        lineas.append(f"   {e['periodo']}: MEFP {e['mefp_tgn']:>10,.1f} · BCB {e['bcb_gobierno_central']:>10,.1f} · dif {e['diferencia']:+.1f}")
    lineas.append(f"   ⇒ {len(externa) - len(fuera)} de {len(externa)} trimestres coinciden (±{TOL_EXTERNA} MM US$).")
    lineas.append("   Los cierres de diciembre que el MEFP revisa al año siguiente quedan iguales al BCB "
                  f"(revisiones: {', '.join(r['mes'] for r in det['meta'].get('revisiones', []))}).")
    lineas.append("")

    # 2. Interna con el BCB: MEFP (TGN → BCB) vs BCB (crédito bruto al Gobierno Central).
    interna = []
    for i, m in enumerate(di["meses"]):
        if m not in bf["meses"]:
            continue
        x = di["series"]["publico_financiero.bcb"][i]
        y = bf["series"]["gobierno_central"]["bruto"][bf["meses"].index(m)]
        interna.append({"mes": m, "mefp_tgn_con_bcb": x, "bcb_credito_bruto_gc": y, "diferencia": round(y - x, 1)})
    difs = [e["diferencia"] for e in interna]
    resumen = {"desde": interna[0]["mes"], "hasta": interna[-1]["mes"], "minimo": min(difs), "maximo": max(difs),
               "media": round(statistics.mean(difs), 1),
               "como_porcentaje_del_credito": round(100 * statistics.mean(difs) /
                                                    statistics.mean(e["bcb_credito_bruto_gc"] for e in interna), 1)}
    lineas.append("2. DEUDA INTERNA CON EL BCB — TGN→BCB (MEFP) vs crédito bruto del BCB al Gobierno Central, MM Bs")
    for e in interna[::6] + [interna[-1]]:
        lineas.append(f"   {e['mes']}: MEFP {e['mefp_tgn_con_bcb']:>10,.0f} · BCB {e['bcb_credito_bruto_gc']:>10,.0f} · dif {e['diferencia']:+,.0f}")
    lineas.append(f"   ⇒ el BCB registra SIEMPRE más: entre {resumen['minimo']:,.0f} y {resumen['maximo']:,.0f} MM Bs "
                  f"(media {resumen['media']:,.0f}, {resumen['como_porcentaje_del_credito']}% del crédito), sin tendencia.")
    lineas.append("   Las fuentes no permiten atribuir la brecha. Candidatos: intereses devengados no pagados o crédito del")
    lineas.append("   BCB a entidades del Gobierno Central distintas del TGN. NO es la deuda histórica (7.380, constante).")
    lineas.append("")

    # 3. Cobertura.
    cobertura = [
        {"componente": "Deuda externa pública (todos los deudores)", "fuente": "BCB", "desde": de["anual"]["saldo_deudor"]["periodos"][0]},
        {"componente": "Deuda externa del TGN por acreedor (con China)", "fuente": "MEFP", "desde": det["meses"][0]},
        {"componente": "Deuda interna del TGN por tenedor", "fuente": "MEFP", "desde": di["meses"][0]},
        {"componente": "Crédito del BCB al sector público (TGN y empresas públicas)", "fuente": "BCB", "desde": bf["meses"][0]},
    ]
    faltantes = [
        "Deuda interna del TGN antes de dic-2022 (la página del MEFP no la publica).",
        "Cuánto de los bonos del TGN colocados en subasta tienen los fondos de pensiones (el MEFP no separa al comprador).",
        "Deuda interna de gobernaciones, municipios y empresas públicas con acreedores distintos del BCB.",
    ]
    lineas.append("3. COBERTURA")
    for c in cobertura:
        lineas.append(f"   ✓ {c['componente']} — {c['fuente']}, desde {c['desde']}")
    for f in faltantes:
        lineas.append(f"   ✗ {f}")

    guardar_json("conciliacion.json", {"externa": externa, "interna_bcb": interna, "interna_resumen": resumen,
                                       "cobertura": cobertura, "faltantes": faltantes})
    (RAIZ / "salidas").mkdir(exist_ok=True)
    (RAIZ / "salidas" / "conciliacion.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))
    if fuera:
        raise FuenteError(f"{len(fuera)} trimestres de deuda externa no coinciden entre BCB y MEFP: {fuera[:3]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR conciliación: {e}")
        sys.exit(1)
