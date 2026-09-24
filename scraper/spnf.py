"""
Operaciones consolidadas del Sector Público No Financiero (SPNF), Gobierno General y
Empresas Públicas — flujo de caja mensual, 2017 en adelante.

Fuente: MEFP, «Ejecución Sector Público No Financiero»
(https://www.economiayfinanzas.gob.bo/index.php/ejecucion-sector-publico-no-financiero).
Un Excel por año (`SPNFGOBEMP<año>…xlsx`) con tres hojas: SPNF, GOB (Gobierno General)
y EMP (Empresas Públicas); meses en columnas, con subtotales trimestrales y total.
El del año en curso se reemplaza cada mes (hoy llega a julio de 2026).

Lo que este parser garantiza (y por qué):
- Cada fila se identifica por su ROTULO DENTRO DE SU SECCIÓN: «TRANSFERENCIAS
  CORRIENTES» aparece dos veces, una en ingresos y otra en egresos.
- Los montos vienen como TEXTO en varias celdas: se convierten, no se descartan.
- Se verifican, mes a mes y sector a sector, las identidades contables del cuadro
  (ingresos − egresos = resultado; financiamiento = −resultado = externo + interno;
  cada total = suma de sus partes; SPNF = GG + EP en el resultado). Si alguna no cierra,
  el scraper se detiene: un cuadro que no suma no se publica.

Definición derivada (no está en el cuadro, se DECLARA):
  resultado primario = resultado global + intereses de deuda externa + intereses de
  deuda interna. Es el resultado antes de pagar la deuda heredada.
Salida: data/spnf.json
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from urllib.parse import unquote

import openpyxl

from comun import (FUENTES, FuenteError, descargar, guardar_json, huella, norm, num,
                   registrar, verificar_frescura)

PAGINA = "https://www.economiayfinanzas.gob.bo/index.php/ejecucion-sector-publico-no-financiero"
ANIO_INICIAL = 2017
MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
TOL = 1.0   # millones de Bs: el cuadro redondea cada celda por separado

# (sección, rótulo normalizado) → clave. Las secciones se abren con su fila de total.
ROTULOS = {
    ("ing", "INGRESOS TOTALES"): "ingresos_totales",
    ("ing", "INGRESOS CORRIENTES"): "ingresos_corrientes",
    ("ing", "INGRESOS TRIBUTARIOS"): "tributarios",
    ("ing", "IMPUESTOS S/ HIDROCARBUROS"): "impuestos_hidrocarburos",
    ("ing", "IMPUESTOS SOBRE HIDROCARBUROS"): "impuestos_hidrocarburos",
    ("ing", "HIDROCARBUROS"): "venta_hidrocarburos",
    ("ing", "VENTA DE HIDROCARBUROS"): "venta_hidrocarburos",
    ("ing", "OTRAS EMPRESAS"): "venta_otras_empresas",
    ("ing", "VENTA DE BIENES Y SERVICIOS"): "venta_bienes_servicios",
    ("ing", "TRANSFERENCIAS CORRIENTES"): "transferencias_recibidas",
    ("ing", "OTROS INGRESOS CORRIENTES"): "otros_ingresos_corrientes",
    ("ing", "INGRESOS DE CAPITAL"): "ingresos_capital",
    ("egr", "EGRESOS TOTALES"): "egresos_totales",
    ("egr", "EGRESOS CORRIENTES"): "egresos_corrientes",
    ("egr", "SERVICIOS PERSONALES"): "servicios_personales",
    ("egr", "BIENES Y SERVICIOS"): "bienes_servicios",
    ("egr", "INTERESES DEUDA EXTERNA"): "intereses_externa",
    ("egr", "INTERESES DEUDA INTERNA"): "intereses_interna",
    ("egr", "TRANSFERENCIAS CORRIENTES"): "transferencias_pagadas",
    ("egr", "PAGO DE TRIBUTOS (INC. IVA YPFB)"): "pago_tributos",
    ("egr", "REGALIAS E IMP. HIDROCARBUROS"): "regalias_impuestos_hidrocarburos",
    ("egr", "OTROS EGRESOS CORRIENTES"): "otros_egresos_corrientes",
    ("egr", "GASTOS NO IDENTIFICADOS"): "gastos_no_identificados",
    ("egr", "EGRESOS DE CAPITAL"): "egresos_capital",
    ("res", "SUP (DEF) CORRIENTE"): "resultado_corriente",
    ("res", "SUP (DEF) GLOBAL"): "resultado_global",
    ("fin", "FINANCIAMIENTO"): "financiamiento",
    ("fin", "CREDITO EXTERNO NETO"): "credito_externo_neto",
    ("fin", "CREDITO INTERNO NETO"): "credito_interno_neto",
    ("fin", "OTRO TIPO DE FINANCIAMIENTO"): "otro_financiamiento",
}
APERTURAS = {"INGRESOS TOTALES": "ing", "EGRESOS TOTALES": "egr",
             "SUP (DEF) CORRIENTE": "res", "FINANCIAMIENTO": "fin"}
# Qué suma cada total en cada hoja (las hojas no tienen las mismas partidas).
PARTES_ING = {
    "spnf": ["tributarios", "impuestos_hidrocarburos", "venta_hidrocarburos", "venta_otras_empresas",
             "transferencias_recibidas", "otros_ingresos_corrientes"],
    "gg": ["tributarios", "impuestos_hidrocarburos", "venta_bienes_servicios", "transferencias_recibidas",
           "otros_ingresos_corrientes"],
    "ep": ["venta_hidrocarburos", "venta_otras_empresas", "transferencias_recibidas", "otros_ingresos_corrientes"],
}
PARTES_EGR = {
    "spnf": ["servicios_personales", "bienes_servicios", "intereses_externa", "intereses_interna",
             "transferencias_pagadas", "otros_egresos_corrientes", "gastos_no_identificados"],
    "gg": ["servicios_personales", "bienes_servicios", "intereses_externa", "intereses_interna",
           "transferencias_pagadas", "otros_egresos_corrientes", "gastos_no_identificados"],
    "ep": ["servicios_personales", "bienes_servicios", "intereses_externa", "intereses_interna",
           "pago_tributos", "regalias_impuestos_hidrocarburos", "transferencias_pagadas",
           "otros_egresos_corrientes", "gastos_no_identificados"],
}
HOJAS = {"SPNF": "spnf", "GOB": "gg", "EMP": "ep"}


def enlaces_por_anio() -> dict[int, str]:
    pag = descargar(PAGINA, FUENTES / "mefp_spnf" / "_pagina.html").decode("utf-8", "ignore")
    por_anio: dict[int, str] = {}
    for href in re.findall(r'href="([^"]+\.xlsx)"', pag):
        m = re.search(r"SPNFGOBEMP(\d{4})", unquote(href))
        if not m or int(m.group(1)) < ANIO_INICIAL:
            continue
        url = href if href.startswith("http") else "https://www.economiayfinanzas.gob.bo" + href
        anio = int(m.group(1))
        # Si un año tiene más de un archivo, gana el subido más tarde (carpeta files/AAAA-MM/).
        carpeta = lambda u: re.search(r"files/(\d{4}-\d{2})/", u).group(1) if re.search(r"files/(\d{4}-\d{2})/", u) else ""
        if anio not in por_anio or carpeta(url) > carpeta(por_anio[anio]):
            por_anio[anio] = url
    faltan = [a for a in range(ANIO_INICIAL, max(por_anio) + 1) if a not in por_anio]
    if faltan:
        raise FuenteError(f"la página del MEFP no enlaza los años {faltan}")
    return por_anio


def rotulo(fila) -> str | None:
    for c in fila:
        if isinstance(c, str) and c.strip() and not re.fullmatch(r"[=\-<1 ]+", c.strip()):
            return c
    return None


def leer_hoja(ws) -> tuple[dict, dict, str]:
    filas = list(ws.iter_rows(values_only=True))
    h = next((i for i, f in enumerate(filas) if any(norm(c) == "ENE" for c in f)), None)
    if h is None:
        raise FuenteError(f"hoja {ws.title}: no encuentro la fila de meses")
    col_mes = {MESES.index(norm(c)) + 1: j for j, c in enumerate(filas[h]) if norm(c) in MESES}
    col_total = next((j for j, c in enumerate(filas[h]) if norm(c) == "TOTAL"), None)
    corte = next((str(c).strip() for f in filas[:h] for c in f
                  if isinstance(c, str) and re.search(r"(PRELIMINAR|\d{4})", c, re.I)
                  and any(m in norm(c) for m in ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
                                                  "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"))), "")
    seccion, valores, totales = None, {}, {}
    for f in filas[h + 1:]:
        lab = rotulo(f)
        if not lab:
            continue
        n = norm(lab).rstrip(" 1/").strip()
        n = re.sub(r"\s*1/$", "", n)
        if n in APERTURAS:
            seccion = APERTURAS[n]
        clave = ROTULOS.get((seccion, n))
        if clave is None or clave in valores:      # la primera aparición manda
            continue
        valores[clave] = {m: num(f[j]) for m, j in col_mes.items()}
        if col_total is not None:
            totales[clave] = num(f[col_total])
    return valores, totales, corte


def cerca(a, b) -> bool:
    return a is not None and b is not None and abs(a - b) <= TOL


def main() -> int:
    enlaces = enlaces_por_anio()
    datos: dict[str, dict[str, dict[str, float]]] = {"spnf": {}, "gg": {}, "ep": {}}
    procedencia, cortes, errores = {}, {}, []
    for anio, url in sorted(enlaces.items()):
        ruta = FUENTES / "mefp_spnf" / f"SPNFGOBEMP{anio}.xlsx"
        crudo = descargar(url, ruta)
        procedencia[anio] = {"url": url, "huella": huella(crudo)}
        wb = openpyxl.load_workbook(ruta, data_only=True)
        vistos = set()
        for ws in wb.worksheets:
            sector = next((v for k, v in HOJAS.items() if ws.title.upper().startswith(k)), None)
            if sector is None:
                continue
            vistos.add(sector)
            valores, totales, corte = leer_hoja(ws)
            if sector == "spnf":
                cortes[anio] = corte
            for clave, por_mes in valores.items():
                meses_con_dato = [m for m, v in por_mes.items() if v is not None]
                for m in meses_con_dato:
                    datos[sector].setdefault(clave, {})[f"{anio}-{m:02d}"] = por_mes[m]
                # El TOTAL del cuadro tiene que ser la suma de sus meses.
                if totales.get(clave) is not None and meses_con_dato:
                    s = sum(por_mes[m] for m in meses_con_dato)
                    if abs(s - totales[clave]) > TOL * 3:
                        errores.append(f"{anio} {sector} {clave}: TOTAL {totales[clave]:,.1f} ≠ suma de meses {s:,.1f}")
        if vistos != {"spnf", "gg", "ep"}:
            raise FuenteError(f"{anio}: faltan hojas {sorted({'spnf', 'gg', 'ep'} - vistos)}")

    meses = sorted({m for s in datos.values() for c in s.values() for m in c})
    # Un mes entra sólo si las tres hojas lo traen: no se mezcla un SPNF de julio con un GG de junio.
    meses = [m for m in meses if all(m in datos[s].get("resultado_global", {}) for s in datos)]
    if meses[0] != f"{ANIO_INICIAL}-01":
        raise FuenteError(f"la serie empieza en {meses[0]}, no en {ANIO_INICIAL}-01")

    def v(sector, clave, m):
        return datos[sector].get(clave, {}).get(m)

    for m in meses:
        for s in datos:
            it, ic, ik = v(s, "ingresos_totales", m), v(s, "ingresos_corrientes", m), v(s, "ingresos_capital", m)
            et, ec, ek = v(s, "egresos_totales", m), v(s, "egresos_corrientes", m), v(s, "egresos_capital", m)
            rg, rc = v(s, "resultado_global", m), v(s, "resultado_corriente", m)
            fi = v(s, "financiamiento", m)
            fx, fn, fo = v(s, "credito_externo_neto", m), v(s, "credito_interno_neto", m), v(s, "otro_financiamiento", m) or 0
            pruebas = [
                ("ingresos = corrientes + capital", it, (ic or 0) + (ik or 0)),
                ("egresos = corrientes + capital", et, (ec or 0) + (ek or 0)),
                ("resultado global = ingresos − egresos", rg, (it or 0) - (et or 0)),
                ("resultado corriente = ing. corr. − egr. corr.", rc, (ic or 0) - (ec or 0)),
                ("financiamiento = −resultado global", fi, -(rg or 0)),
                ("financiamiento = externo + interno (+ otro)", fi, (fx or 0) + (fn or 0) + fo),
                ("ingresos corrientes = suma de partidas", ic, sum(v(s, k, m) or 0 for k in PARTES_ING[s])),
                ("egresos corrientes = suma de partidas", ec, sum(v(s, k, m) or 0 for k in PARTES_EGR[s])),
            ]
            for nombre, a, b in pruebas:
                if not cerca(a, b):
                    errores.append(f"{m} {s}: {nombre} ({a} vs {b:,.1f})")
        # La consolidación cancela las transferencias entre GG y EP: el resultado sí suma.
        a, b = v("spnf", "resultado_global", m), (v("gg", "resultado_global", m) or 0) + (v("ep", "resultado_global", m) or 0)
        if not cerca(a, b):
            errores.append(f"{m}: resultado SPNF {a} ≠ GG + EP {b:,.1f}")

    if errores:
        print(f"   {len(errores)} identidades no cierran:")
        for e in errores[:40]:
            print("    ·", e)
        raise FuenteError("el cuadro del SPNF no suma; no se publica")

    series = {}
    for s, claves in datos.items():
        series[s] = {k: [None if claves[k].get(m) is None else round(claves[k][m], 1) for m in meses]
                     for k in sorted(claves)}
        # Resultado primario (declarado arriba).
        series[s]["resultado_primario"] = [
            None if g is None else round(g + (ie or 0) + (ii or 0), 1)
            for g, ie, ii in zip(series[s]["resultado_global"], series[s]["intereses_externa"],
                                 series[s]["intereses_interna"])]

    ultimo = meses[-1]
    guardar_json("spnf.json", {
        "meta": {
            "indicador": "Operaciones consolidadas del SPNF, Gobierno General y Empresas Públicas",
            "unidad": "millones de bolivianos", "base": "flujo de caja, mensual",
            "fuente": "Ministerio de Economía y Finanzas Públicas (MEFP)", "pagina": PAGINA,
            "corte": cortes.get(int(ultimo[:4]), ""), "ultimo_mes": ultimo,
            "sectores": {"spnf": "Sector Público No Financiero", "gg": "Gobierno General",
                         "ep": "Empresas Públicas"},
            "definiciones": {
                "resultado_primario": "resultado global + intereses de deuda externa + intereses de deuda interna",
                "signo": "resultado negativo = déficit; financiamiento positivo = el sector se endeuda",
            },
            "archivos": {str(a): p for a, p in procedencia.items()},
        },
        "meses": meses,
        "series": series,
    })
    registrar("spnf", pagina=PAGINA, ultimo_dato=ultimo, corte=cortes.get(int(ultimo[:4]), ""),
              archivos=len(procedencia), meses=len(meses))
    print(f"   SPNF {meses[0]}–{ultimo} ({len(meses)} meses) · identidades: todas cierran")
    # Mensual con ~6-8 semanas de rezago: más de 4 meses sin mes nuevo es anomalía.
    verificar_frescura("SPNF", dt.date(int(ultimo[:4]), int(ultimo[5:]), 1), max_meses=4)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR SPNF: {e}")
        sys.exit(1)
