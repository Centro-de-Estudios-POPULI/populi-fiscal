"""
Indicadores derivados del Monitor Fiscal: todo lo que los gráficos y el encabezado
muestran y que no está tal cual en una fuente (ratios sobre el PIB, acumulados, deuda
en bolivianos, cifras del encabezado). Lee SÓLO los JSON de data/: no descarga nada.

Decisiones metodológicas (declaradas, no escondidas):
- PIB: nominal, año de referencia 2017 (INE). Un ratio sólo se calcula si el PIB de
  ese año existe; el año en curso se muestra en bolivianos hasta que el INE publique.
- Flujos fiscales: caja, SPNF consolidado (MEFP). Resultado negativo = déficit.
- Resultado primario = global + intereses de deuda externa e interna.
- Deuda en dólares → bolivianos: tipo de cambio oficial de COMPRA, Bs 6,86 por dólar
  hasta el 26-jun-2026 (régimen fijo); desde el 27-jun-2026, el tipo de cambio oficial
  (TCO) vigente en la fecha, del repositorio Dolar_Bolivia.
- Deuda bruta del TGN = deuda externa del TGN (MEFP) + deuda interna del TGN (MEFP).
  Incluye la deuda con el BCB (que es parte del sector público): es deuda BRUTA.
Salida: data/indicadores.json
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request

from comun import DATA, FuenteError, guardar_json

TC_FIJO = 6.86
FIN_TC_FIJO = "2026-06-26"
URL_TCO = "https://centro-de-estudios-populi.github.io/Dolar_Bolivia/data/tco.json"
_tco = None


def tipo_cambio(fecha: str) -> float:
    """Tipo de cambio oficial vigente al cierre de `fecha` (AAAA-MM-DD)."""
    global _tco
    if fecha <= FIN_TC_FIJO:
        return TC_FIJO
    if _tco is None:
        with urllib.request.urlopen(urllib.request.Request(URL_TCO, headers={"User-Agent": "populi-fiscal"}), timeout=60) as r:
            _tco = sorted((x.get("vig") or x["f"], x["tco"]) for x in json.load(r)["serie"] if x.get("tco"))
    previos = [v for f, v in _tco if f <= fecha]
    if not previos:
        raise FuenteError(f"no hay tipo de cambio oficial para {fecha}")
    return previos[-1]


def fin_de_mes(ym: str) -> str:
    a, m = int(ym[:4]), int(ym[5:])
    sig = dt.date(a + (m == 12), m % 12 + 1, 1)
    return (sig - dt.timedelta(days=1)).isoformat()


def cargar(n):
    return json.loads((DATA / n).read_text(encoding="utf-8"))


def pct(x, base):
    return None if x is None or not base else round(100 * x / base, 2)


def main() -> int:
    spnf, pib, bf, de, det, di, embi, osf = (cargar(n) for n in (
        "spnf.json", "pib.json", "bcb_financiamiento.json", "deuda_externa.json", "deuda_externa_tgn.json",
        "deuda_interna.json", "embi.json", "bcb_osf.json"))
    M = spnf["meses"]
    S = spnf["series"]
    pib_anual = {a["anio"]: a["pib"] for a in pib["anual"]}

    def suma(sector, clave, anio, hasta_mes=12):
        idx = [i for i, m in enumerate(M) if m.startswith(f"{anio}-") and int(m[5:]) <= hasta_mes]
        vals = [S[sector][clave][i] for i in idx]
        return None if not vals or any(v is None for v in vals) else round(sum(vals), 1), len(idx)

    anios = sorted({int(m[:4]) for m in M})
    completos = [a for a in anios if suma("spnf", "resultado_global", a)[1] == 12]

    # ── Anual ────────────────────────────────────────────────────────────────
    ING = [("tributarios", ["tributarios"]), ("impuestos_hidrocarburos", ["impuestos_hidrocarburos"]),
           ("venta_hidrocarburos", ["venta_hidrocarburos"]), ("venta_otras_empresas", ["venta_otras_empresas"]),
           ("otros", ["transferencias_recibidas", "otros_ingresos_corrientes", "ingresos_capital"])]
    EGR = [("servicios_personales", ["servicios_personales"]), ("bienes_servicios", ["bienes_servicios"]),
           ("intereses", ["intereses_externa", "intereses_interna"]), ("transferencias", ["transferencias_pagadas"]),
           ("otros_corrientes", ["otros_egresos_corrientes", "gastos_no_identificados"]),
           ("capital", ["egresos_capital"])]
    de_anual = de["anual"]["saldo_deudor"]
    anual = []
    for a in completos:
        y = pib_anual.get(a)
        fila = {"anio": a, "pib": y}
        for sec in ("spnf", "gg", "ep"):
            g = suma(sec, "resultado_global", a)[0]
            p = suma(sec, "resultado_primario", a)[0]
            fila[sec] = {"global": g, "primario": p, "global_pib": pct(g, y), "primario_pib": pct(p, y)}
        it = suma("spnf", "ingresos_totales", a)[0]
        et = suma("spnf", "egresos_totales", a)[0]
        intereses = suma("spnf", "intereses_externa", a)[0] + suma("spnf", "intereses_interna", a)[0]
        fila["spnf"].update({"ingresos": it, "egresos": et, "ingresos_pib": pct(it, y), "egresos_pib": pct(et, y),
                             "intereses": round(intereses, 1), "intereses_pib": pct(intereses, y),
                             "intereses_sobre_ingresos": pct(intereses, it)})
        fila["ingresos_pib"] = {k: pct(sum(suma("spnf", c, a)[0] for c in cs), y) for k, cs in ING}
        fila["egresos_pib"] = {k: pct(sum(suma("spnf", c, a)[0] for c in cs), y) for k, cs in EGR}
        fx, fn = suma("spnf", "credito_externo_neto", a)[0], suma("spnf", "credito_interno_neto", a)[0]
        fo = suma("spnf", "otro_financiamiento", a)[0] if "otro_financiamiento" in S["spnf"] else 0
        fila["financiamiento"] = {"externo": fx, "interno": fn, "otro": fo or 0,
                                  "externo_pib": pct(fx, y), "interno_pib": pct(fn, y), "otro_pib": pct(fo or 0, y)}
        # Deuda externa pública (BCB), saldo a fin de año.
        if str(a) in de_anual["periodos"]:
            i = de_anual["periodos"].index(str(a))
            tc = tipo_cambio(f"{a}-12-31")
            ext = {k: de_anual[k][i] for k in ("total", "gobierno_central", "empresas_publicas", "gobiernos_locales")}
            fila["deuda_externa"] = {"usd": ext, "tc": tc, "total_bs": round(ext["total"] * tc, 1),
                                     "total_pib": pct(ext["total"] * tc, y)}
        # Deuda interna del TGN (MEFP), disponible desde dic-2022.
        dic = f"{a}-12"
        if dic in di["meses"]:
            j = di["meses"].index(dic)
            interna = di["total"][j]
            fila["deuda_interna_tgn"] = {"bs": interna, "pib": pct(interna, y),
                                         "con_bcb": di["series"]["publico_financiero.bcb"][j]}
            if dic in det["meses"]:
                ext_tgn = det["series"]["total"][det["meses"].index(dic)] * tipo_cambio(f"{a}-12-31")
                bruta = interna + ext_tgn
                fila["deuda_bruta_tgn"] = {"bs": round(bruta, 1), "pib": pct(bruta, y),
                                           "externa_bs": round(ext_tgn, 1), "interna_bs": interna}
        # Crédito neto del BCB al sector público, fin de año.
        if dic in bf["meses"]:
            k = bf["meses"].index(dic)
            bcb = {s: bf["series"][s]["neto"][k] for s in ("total", "gobierno_central", "empresas_publicas")}
            fila["bcb_neto"] = {**bcb, "total_pib": pct(bcb["total"], y)}
        anual.append(fila)

    # ── Acumulado en el año, mes a mes (una línea por año) ───────────────────
    acumulado = []
    for a in anios:
        idx = [i for i, m in enumerate(M) if m.startswith(f"{a}-")]
        g = p = 0.0
        serie = []
        for i in idx:
            g += S["spnf"]["resultado_global"][i]
            p += S["spnf"]["resultado_primario"][i]
            serie.append({"mes": int(M[i][5:]), "global": round(g, 1), "primario": round(p, 1),
                          "global_pib": pct(g, pib_anual.get(a)), "primario_pib": pct(p, pib_anual.get(a))})
        acumulado.append({"anio": a, "pib": pib_anual.get(a), "completo": len(idx) == 12, "meses": serie})

    # ── Año en curso contra el mismo período del año anterior ────────────────
    ult = M[-1]
    a_ult, m_ult = int(ult[:4]), int(ult[5:])
    parcial = None
    if a_ult not in completos:
        actual = {k: suma("spnf", k, a_ult, m_ult)[0] for k in ("resultado_global", "resultado_primario",
                                                               "ingresos_totales", "egresos_totales")}
        previo = {k: suma("spnf", k, a_ult - 1, m_ult)[0] for k in actual}
        parcial = {"anio": a_ult, "hasta_mes": m_ult, "actual": actual, "mismo_periodo_anterior": previo}

    # ── Encabezado (KPIs) ────────────────────────────────────────────────────
    u = anual[-1]
    kpis = {
        "deficit": {"valor_pib": u["spnf"]["global_pib"], "anio": u["anio"],
                    "primario_pib": u["spnf"]["primario_pib"], "parcial": parcial},
        "deuda_bruta_tgn": {"valor_pib": u.get("deuda_bruta_tgn", {}).get("pib"), "anio": u["anio"],
                            "bs": u.get("deuda_bruta_tgn", {}).get("bs")},
        "bcb_neto": {"valor": bf["series"]["total"]["neto"][-1], "mes": bf["meses"][-1],
                     "hace_un_anio": bf["series"]["total"]["neto"][-13] if len(bf["meses"]) > 12 else None},
        "riesgo_pais": {"valor": embi["series"]["Bolivia"][-1], "fecha": embi["fechas"][-1],
                        "latinoamerica": embi["series"]["Latinoamérica"][-1]},
    }
    guardar_json("indicadores.json", {
        "meta": {"generado": dt.date.today().isoformat(), "ultimo_mes_spnf": ult,
                 "pib_hasta": pib["meta"]["ultimo_trimestre"],
                 "tipo_cambio": {"fijo": TC_FIJO, "hasta": FIN_TC_FIJO, "despues": "TCO vigente (Dolar_Bolivia)"},
                 "definiciones": {
                     "deficit": "resultado global del SPNF (caja), en % del PIB nominal base 2017",
                     "deuda_bruta_tgn": "deuda externa del TGN (MEFP, a Bs 6,86/US$) + deuda interna del TGN (MEFP); incluye la deuda con el BCB",
                     "bcb_neto": "crédito del BCB al sector público menos sus depósitos en el BCB (BCB)",
                     "riesgo_pais": "spread del EMBI Global Diversified de Bolivia (J.P. Morgan vía BCRD)"}},
        "anual": anual, "acumulado": acumulado, "parcial": parcial, "kpis": kpis,
        "osf": {"meses": osf["meses"], "credito_neto_gc": osf["series"]["credito_neto_gobierno_central"]},
    })
    print(f"   indicadores {completos[0]}–{completos[-1]} (+ {ult} parcial) · "
          f"déficit {u['anio']}: {u['spnf']['global_pib']}% PIB · deuda bruta TGN: {kpis['deuda_bruta_tgn']['valor_pib']}% PIB")
    if parcial:
        print(f"   {a_ult} ene–{m_ult:02d}: global {parcial['actual']['resultado_global']:,.0f} MM Bs "
              f"(mismo período {a_ult - 1}: {parcial['mismo_periodo_anterior']['resultado_global']:,.0f})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR indicadores: {e}")
        sys.exit(1)
