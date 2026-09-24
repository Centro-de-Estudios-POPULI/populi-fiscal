"""
Crédito de las Otras Sociedades Financieras (OSF) al Gobierno Central — BCB.

Fuente: BCB, Sector Monetario › Balances Consolidados ›
«15. Cuentas monetarias de Otras Sociedades Financieras.xlsx» (mensual desde dic-2021,
meses en COLUMNAS), en millones de bolivianos.

Por qué está: el MEFP registra la deuda del TGN con los fondos de pensiones dentro de
«Mercado financiero (subasta)», sin separar al comprador (su línea «AFPs» son los viejos
Bonos AFP y está en cero). Las OSF —fondos de pensiones, aseguradoras, fondos de
inversión y otras— son el sector que agrupa a esos tenedores, y su pasivo principal
son «reservas técnicas de seguros», que en la metodología del FMI incluye los derechos
de pensión. ⚠️ Es un AGREGADO: no aísla a los fondos de pensiones. Se publica con ese
rótulo exacto.
Salida: data/bcb_osf.json
"""
from __future__ import annotations

import datetime as dt
import sys
from urllib.parse import quote

import openpyxl

from comun import (FUENTES, FuenteError, descargar, guardar_json, huella, norm, num,
                   registrar, verificar_frescura)

PAGINA = "https://www.bcb.gob.bo/?q=content/sector-monetario"
URL = "https://www.bcb.gob.bo" + quote(
    "/webdocs/sector_monetario/Balances Consolidados/15. Cuentas monetarias de Otras Sociedades Financieras.xlsx")
FILAS = {"CREDITO INTERNO NETO CON EL GOBIERNO CENTRAL": "credito_neto_gobierno_central",
         "RESERVAS TECNICAS DE SEGUROS": "reservas_tecnicas"}


def main() -> int:
    ruta = FUENTES / "bcb_monetario" / "osf.xlsx"
    crudo = descargar(URL, ruta, referer=PAGINA)
    ws = openpyxl.load_workbook(ruta, data_only=True).worksheets[0]
    filas = list(ws.iter_rows(values_only=True))
    h = next((i for i, f in enumerate(filas[:10]) if sum(isinstance(c, dt.datetime) for c in f) >= 6), None)
    if h is None:
        raise FuenteError("no encuentro la fila de fechas (el cuadro va con los meses en columnas)")
    cols = {j: c.strftime("%Y-%m") for j, c in enumerate(filas[h]) if isinstance(c, dt.datetime)}
    series, siguiente = {}, None
    for f in filas[h + 1:]:
        lab = next((c for c in f if isinstance(c, str) and c.strip()), None)
        if not lab:
            continue
        n = norm(lab)
        if siguiente:                       # la fila «Crédito» que sigue al neto
            if n == "CREDITO":
                series["credito_bruto_gobierno_central"] = {m: num(f[j]) for j, m in cols.items()}
            siguiente = None
        if n in FILAS:
            series[FILAS[n]] = {m: num(f[j]) for j, m in cols.items()}
            siguiente = n.startswith("CREDITO INTERNO")
    faltan = set(FILAS.values()) - set(series)
    if faltan:
        raise FuenteError(f"faltan las filas {faltan}")
    meses = sorted(m for m in cols.values() if series["credito_neto_gobierno_central"].get(m) is not None)
    salida = {k: [None if v.get(m) is None else round(v[m], 1) for m in meses] for k, v in series.items()}
    guardar_json("bcb_osf.json", {
        "meta": {"indicador": "Otras sociedades financieras: crédito al Gobierno Central",
                 "unidad": "millones de bolivianos", "fuente": "Banco Central de Bolivia (BCB)",
                 "url": URL, "pagina": PAGINA, "ultimo_mes": meses[-1],
                 "nota": "Agrega fondos de pensiones, aseguradoras, fondos de inversión y otras sociedades financieras "
                         "no bancarias: no aísla a los fondos de pensiones."},
        "meses": meses, "series": salida,
    })
    registrar("bcb_osf", url=URL, huella=huella(crudo), ultimo_dato=meses[-1])
    print(f"   OSF {meses[0]}–{meses[-1]}: crédito neto al Gobierno Central {salida['credito_neto_gobierno_central'][-1]:,.0f} MM Bs")
    u = meses[-1]
    verificar_frescura("OSF", dt.date(int(u[:4]), int(u[5:]), 1), max_meses=12)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR OSF: {e}")
        sys.exit(1)
