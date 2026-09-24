"""
Deuda externa pública de mediano y largo plazo — BCB.

Fuente: BCB, Sector Externo › E. Deuda Externa (https://www.bcb.gob.bo/?q=content/sector-externo-0).
Ocho cuadros de la misma familia, cada uno con una hoja trimestral y otra anual, en
millones de dólares:
  saldo adeudado · servicio de la deuda · desembolsos · transferencia neta
  × por DEUDOR (gobierno central, empresas públicas, gobiernos locales…)
  × por ACREEDOR (BID, Banco Mundial, CAF, bilaterales, títulos de deuda…)

Controles:
- Cada columna se ubica por su rótulo (el más bajo del encabezado); «OTROS» y
  «SUBTOTAL» se repiten y se distinguen por su orden.
- Las partes suman su subtotal y su total.
- El total POR DEUDOR es igual al total POR ACREEDOR en cada período: son dos cortes
  del mismo stock (o flujo).
Nota: el BCB NO separa a China entre los bilaterales (va en «otros»). El detalle por
país del TGN está en el cuadro del MEFP (deuda_tgn_mefp.py).
Salida: data/deuda_externa.json
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from urllib.parse import quote

import openpyxl

from comun import (FUENTES, FuenteError, descargar, guardar_json, huella, norm, num,
                   registrar, verificar_frescura)

PAGINA = "https://www.bcb.gob.bo/?q=content/sector-externo-0"
BASE = "/webdocs/sector_externo/E Deuda Externa/"
CUADROS = {
    ("saldo", "deudor"): "Externa publica de mediano y largo plazo saldo adeudado por deudor.xlsx",
    ("saldo", "acreedor"): "Externa publica de mediano y largo plazo saldo adeudado por acreedor.xlsx",
    ("servicio", "deudor"): "Externa publica de mediano y largo plazo - servicio de la deuda por deudor.xlsx",
    ("servicio", "acreedor"): "Externa publica de mediano y largo plazo servicio de la deuda por acreedor.xlsx",
    ("desembolsos", "deudor"): "Externa publica de mediano y largo plazo desembolsos por deudor.xlsx",
    ("desembolsos", "acreedor"): "Externa publica de mediano y largo plazo - desembolsos por acreedor.xlsx",
    ("transferencia_neta", "deudor"): "Externa publica de mediano y largo plazo transferencia neta por deudor.xlsx",
    ("transferencia_neta", "acreedor"): "Externa publica de mediano y largo plazo transferencia neta por acreedor.xlsx",
}
DEUDOR = [("GOBIERNOS LOCALES", "gobiernos_locales"), ("GOBIERNO LOCALES", "gobiernos_locales"),
          ("GOBIERNO CENTRAL", "gobierno_central"), ("INST. PUB. NO FIN", "inst_publicas_no_financieras"),
          ("EMP. PUB. Y MIXTAS", "empresas_publicas"), ("SUBTOTAL#1", "spnf"),
          ("INST. PUB. FINAN", "inst_publicas_financieras"), ("SUBTOTAL#2", "sector_publico_financiero"),
          ("SECTOR PRIV. CON GARANTIA", "privado_con_garantia"), ("TOTAL", "total")]
ACREEDOR = [("BID", "bid"), ("BM", "banco_mundial"), ("CAF", "caf"), ("OTROS#1", "multilateral_otros"),
            ("SUBTOTAL#1", "multilateral"), ("ALEMANIA", "alemania"), ("BELGICA", "belgica"),
            ("BRASIL", "brasil"), ("ESPANA", "espana"), ("ESTADOS UNIDOS", "estados_unidos"),
            ("JAPON", "japon"), ("OTROS#2", "bilateral_otros"), ("SUBTOTAL#2", "bilateral"),
            ("PRIVADOS", "privados"), ("TITULOS DE DEUDA", "titulos_de_deuda"), ("TOTAL", "total")]
SUMAS = {
    "deudor": [("spnf", ["gobiernos_locales", "gobierno_central", "inst_publicas_no_financieras", "empresas_publicas"]),
               ("sector_publico_financiero", ["inst_publicas_financieras"]),
               ("total", ["spnf", "sector_publico_financiero", "privado_con_garantia"])],
    "acreedor": [("multilateral", ["bid", "banco_mundial", "caf", "multilateral_otros"]),
                 ("bilateral", ["alemania", "belgica", "brasil", "espana", "estados_unidos", "japon", "bilateral_otros"]),
                 ("total", ["multilateral", "bilateral", "privados", "titulos_de_deuda"])],
}
TOL = 0.6   # millones de US$
DESDE_ESTRICTO = 2017   # desde acá una suma que no cierra detiene todo; antes se registra


def leer_hoja(ws, corte: str) -> tuple[list[str], dict, set]:
    filas = list(ws.iter_rows(values_only=True))
    es_periodo = lambda c: re.match(r"^\d{4}(-T[1-4])?$", str(c).strip()) if c is not None else None
    d0 = next((i for i, f in enumerate(filas) if f and es_periodo(f[0])), None)
    if d0 is None:
        raise FuenteError(f"{ws.title}: no encuentro filas de período")
    # Rótulo de cada columna = la celda de encabezado más BAJA con texto.
    ancho = max(len(f) for f in filas[:d0 + 1])
    rot = {}
    for j in range(2, ancho):
        for i in range(d0 - 1, -1, -1):
            c = filas[i][j] if j < len(filas[i]) else None
            if isinstance(c, str) and c.strip() and not c.strip().startswith("("):
                rot[j] = re.sub(r"[^A-Z0-9 .]", "", norm(c)).strip()
                break
    vistos: dict[str, int] = {}
    etiquetas = {}
    for j, r in sorted(rot.items()):
        base = r.rstrip(". ")
        if base in ("OTROS", "SUBTOTAL"):
            vistos[base] = vistos.get(base, 0) + 1
            base = f"{base}#{vistos[base]}"
        etiquetas[j] = base
    mapa = DEUDOR if corte == "deudor" else ACREEDOR
    col = {}
    for patron, clave in mapa:
        js = [j for j, e in etiquetas.items() if e == patron or (not patron.endswith(("#1", "#2")) and e.startswith(patron + " "))
              or (patron in ("BM",) and e.startswith("BM"))]
        if js and clave not in col:
            col[clave] = js[0]
    faltan = sorted({c for _, c in mapa} - set(col))
    if faltan:
        raise FuenteError(f"{ws.title}: no encuentro las columnas {faltan} (rótulos: {list(etiquetas.values())})")
    periodos, serie, prelim = [], {k: [] for k in col}, set()
    for f in filas[d0:]:
        p = es_periodo(f[0]) if f else None
        if not p:
            continue
        periodo = str(f[0]).strip()
        periodos.append(periodo)
        if isinstance(f[1], str) and "p" in f[1].lower():
            prelim.add(periodo)
        for k, j in col.items():
            serie[k].append(num(f[j]))
    return periodos, serie, prelim


def main() -> int:
    salida = {"anual": {}, "trimestral": {}}
    periodos_ref = {}
    prelim_total = {"anual": set(), "trimestral": set()}
    huellas = {}
    discrepancias: list[str] = []
    for (concepto, corte), archivo in CUADROS.items():
        url = "https://www.bcb.gob.bo" + quote(BASE + archivo)
        ruta = FUENTES / "bcb_deuda_externa" / archivo
        crudo = descargar(url, ruta, referer=PAGINA)
        huellas[f"{concepto}_{corte}"] = huella(crudo)
        wb = openpyxl.load_workbook(ruta, data_only=True)
        for ws in wb.worksheets:
            frec = "trimestral" if "TRIM" in ws.title.upper() else "anual" if "ANUAL" in ws.title.upper() else None
            if frec is None:
                continue
            periodos, serie, prelim = leer_hoja(ws, corte)
            prelim_total[frec] |= prelim
            ref = periodos_ref.setdefault(frec, periodos)
            if periodos != ref:
                # Los cuadros se actualizan juntos; si uno quedó atrás se recorta al período común.
                comun = [p for p in ref if p in periodos]
                print(f"   aviso: {archivo[:50]}… {frec} llega a {periodos[-1]} (otros a {ref[-1]})")
                idx = [periodos.index(p) for p in comun]
                serie = {k: [v[i] for i in idx] for k, v in serie.items()}
                periodos = comun
            errores = []
            for i, p in enumerate(periodos):
                for total, partes in SUMAS[corte]:
                    a, b = serie[total][i], sum(serie[x][i] or 0 for x in partes)
                    if a is None or abs(a - b) > TOL:
                        msg = f"{concepto} por {corte}, {frec} {p}: {total} {a:,.2f} vs suma de partes {b:,.2f}"
                        if int(p[:4]) >= DESDE_ESTRICTO:
                            errores.append(msg)
                        else:
                            discrepancias.append(msg)   # error de la propia fuente, fuera del período del monitor
            if errores:
                raise FuenteError(f"{archivo} ({frec}): {len(errores)} sumas no cierran, p. ej. {errores[:3]}")
            salida[frec][f"{concepto}_{corte}"] = {"periodos": periodos,
                                                   **{k: [None if x is None else round(x, 2) for x in v] for k, v in serie.items()}}
    # Deudor y acreedor son dos cortes del mismo total.
    for frec, cuadros in salida.items():
        for concepto in ("saldo", "servicio", "desembolsos", "transferencia_neta"):
            d, a = cuadros[f"{concepto}_deudor"], cuadros[f"{concepto}_acreedor"]
            comunes = [p for p in d["periodos"] if p in a["periodos"]]
            for p in comunes:
                x, y = d["total"][d["periodos"].index(p)], a["total"][a["periodos"].index(p)]
                if abs((x or 0) - (y or 0)) > TOL:
                    raise FuenteError(f"{concepto} {frec} {p}: total por deudor {x} ≠ por acreedor {y}")
    ult_t = salida["trimestral"]["saldo_deudor"]["periodos"][-1]
    guardar_json("deuda_externa.json", {
        "meta": {"indicador": "Deuda externa pública de mediano y largo plazo",
                 "unidad": "millones de dólares", "fuente": "Banco Central de Bolivia (BCB)",
                 "pagina": PAGINA, "ultimo_trimestre": ult_t,
                 "preliminar": {k: sorted(v) for k, v in prelim_total.items()},
                 "discrepancias_fuente": discrepancias,
                 "notas": {"china": "el BCB incluye a China en «bilateral_otros»",
                           "servicio": "capital + intereses y comisiones pagados",
                           "transferencia_neta": "desembolsos − servicio"}},
        **salida,
    })
    registrar("deuda_externa", pagina=PAGINA, ultimo_dato=ult_t, huellas=huellas,
              discrepancias_fuente=len(discrepancias))
    for d in discrepancias:
        print(f"   discrepancia de la fuente (anterior a {DESDE_ESTRICTO}): {d}")
    s = salida["anual"]["saldo_deudor"]
    print(f"   deuda externa pública {s['periodos'][0]}–{s['periodos'][-1]} (trimestral hasta {ult_t}); "
          f"saldo {s['periodos'][-1]}: {s['total'][-1]:,.0f} MM US$ (Gob. Central {s['gobierno_central'][-1]:,.0f})")
    anio, t = int(ult_t[:4]), int(ult_t[-1])
    verificar_frescura("Deuda externa", dt.date(anio, t * 3, 1), max_meses=7)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR deuda externa: {e}")
        sys.exit(1)
