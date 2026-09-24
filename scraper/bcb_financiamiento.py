"""
Financiamiento del Banco Central de Bolivia al sector público — saldos a fin de mes.

Fuente: BCB, Sector Monetario › Créditos y Depósitos › BCB ›
«3. Financiamiento neto al Sector Público.xlsx». Mensual desde 1987.
Para cada sector (Gobierno Central, Seguridad Social, Gobiernos Locales y Regionales,
Empresas Públicas y el total): crédito BRUTO, DEPÓSITOS en el BCB y crédito NETO
(= bruto − depósitos).

Es la medida de la monetización del déficit: cuánto le presta el BCB al Estado,
descontado lo que el Estado tiene depositado en el propio BCB. Separa el Tesoro
(Gobierno Central) de las empresas públicas, que es lo que el cuadro del MEFP no hace.

⚠️ El Monitor Monetario lee este mismo archivo por COLUMNAS FIJAS. Acá se ubica cada
columna por el rótulo de su sector y de su concepto; si el BCB reordena, se detiene.
Unidad de la fuente: miles de bolivianos → se publica en millones.
Salida: data/bcb_financiamiento.json
"""
from __future__ import annotations

import datetime as dt
import sys
from urllib.parse import quote

import openpyxl

from comun import (FUENTES, FuenteError, descargar, guardar_json, huella, norm, num,
                   registrar, verificar_frescura)

PAGINA = "https://www.bcb.gob.bo/?q=content/sector-monetario"
URL = ("https://www.bcb.gob.bo" + quote(
    "/webdocs/sector_monetario/Créditos y Depósitos/BCB/3. Financiamiento neto al Sector Público.xlsx"))
DESDE = "2000-01"
SECTORES = {"GOBIERNO CENTRAL": "gobierno_central", "SEGURIDAD SOCIAL": "seguridad_social",
            "GOBIERNOS LOCALES": "gobiernos_locales", "EMPRESAS PUBLICAS": "empresas_publicas",
            "TOTAL": "total"}
CONCEPTOS = {"BRUTO": "bruto", "DEPOSITOS": "depositos", "NETO": "neto"}


def leer(ruta):
    ws = openpyxl.load_workbook(ruta, read_only=True, data_only=True).worksheets[0]
    filas = list(ws.iter_rows(values_only=True))
    # Fila de sectores: la que tiene «GOBIERNO CENTRAL». Los rótulos van en la primera
    # columna de su grupo (celdas combinadas): se arrastran hacia la derecha.
    i_sec = next((i for i, f in enumerate(filas[:15]) if any("GOBIERNO" in norm(c) and "CENTRAL" in norm(c) for c in f)), None)
    i_con = next((i for i, f in enumerate(filas[:15]) if sum(norm(c) in CONCEPTOS for c in f) >= 10), None)
    if i_sec is None or i_con is None:
        raise FuenteError("no encuentro los encabezados de sector y de concepto")
    unidad = " ".join(norm(c) for f in filas[:i_sec] for c in f if isinstance(c, str))
    # Las columnas de concepto vienen en tríos Bruto/Depósitos/Neto. Cada trío toma el
    # sector cuyo rótulo cae DENTRO de sus tres columnas (el BCB centra algunos rótulos,
    # como «T O T A L», en la columna del medio: arrastrar desde la izquierda los corre).
    conceptos = [(j, CONCEPTOS[norm(c)]) for j, c in enumerate(filas[i_con]) if norm(c) in CONCEPTOS]
    if [c for _, c in conceptos] != ["bruto", "depositos", "neto"] * (len(conceptos) // 3) or len(conceptos) % 3:
        raise FuenteError(f"los conceptos no vienen en tríos bruto/depósitos/neto: {[c for _, c in conceptos]}")
    col = {}
    for k in range(0, len(conceptos), 3):
        js = [j for j, _ in conceptos[k:k + 3]]
        rot = " ".join(norm(filas[i_sec][j]) for j in range(js[0], js[-1] + 1) if j < len(filas[i_sec]))
        rot = rot.replace(" ", "")
        sector = [v for kk, v in SECTORES.items() if kk.replace(" ", "") in rot]
        if len(sector) != 1:
            raise FuenteError(f"el trío de columnas {js} no tiene un sector inequívoco: «{rot}»")
        for j, c in conceptos[k:k + 3]:
            if (sector[0], c) in col:
                raise FuenteError(f"el sector {sector[0]} aparece dos veces")
            col[(sector[0], c)] = j
    faltan = [(s, c) for s in SECTORES.values() for c in CONCEPTOS.values() if (s, c) not in col]
    if faltan:
        raise FuenteError(f"faltan columnas {faltan}")
    serie = {}
    for f in filas[i_con + 1:]:
        d = f[0]
        if not isinstance(d, dt.datetime):
            continue
        clave = d.strftime("%Y-%m")
        if clave < DESDE:
            continue
        vals = {k: num(f[j]) for k, j in col.items()}
        if vals[("total", "bruto")] is None:
            continue
        serie[clave] = vals
    return serie, unidad


def main() -> int:
    ruta = FUENTES / "bcb_monetario" / "financiamiento_neto_sp.xlsx"
    crudo = descargar(URL, ruta, referer=PAGINA)
    serie, unidad = leer(ruta)
    meses = sorted(serie)
    errores = []
    for m in meses:
        v = serie[m]
        for s in SECTORES.values():
            b, d, n = (v[(s, c)] or 0 for c in ("bruto", "depositos", "neto"))
            if abs(b - d - n) > 2:           # miles de Bs
                errores.append(f"{m} {s}: bruto − depósitos ≠ neto ({b} − {d} vs {n})")
        for c in CONCEPTOS.values():
            partes = sum(v[(s, c)] or 0 for s in SECTORES.values() if s != "total")
            if abs(partes - (v[("total", c)] or 0)) > 5:
                errores.append(f"{m} {c}: la suma de sectores no da el total ({partes} vs {v[('total', c)]})")
    if errores:
        for e in errores[:20]:
            print("    ·", e)
        raise FuenteError(f"{len(errores)} identidades no cierran en el financiamiento del BCB")
    # Unidad: el cuadro está en miles. Se confirma por magnitud (el total bruto de 2025 ronda
    # los 200 mil millones de Bs = 2e8 miles) porque el título no siempre la declara.
    if not ("MILES" in unidad or (serie[meses[-1]][("total", "bruto")] or 0) > 1e7):
        raise FuenteError("no puedo confirmar que el cuadro esté en miles de bolivianos")
    series = {s: {c: [round((serie[m][(s, c)] or 0) / 1000, 1) for m in meses] for c in CONCEPTOS.values()}
              for s in SECTORES.values()}
    guardar_json("bcb_financiamiento.json", {
        "meta": {"indicador": "Financiamiento del BCB al sector público (saldos a fin de mes)",
                 "unidad": "millones de bolivianos", "fuente": "Banco Central de Bolivia (BCB)",
                 "url": URL, "pagina": PAGINA, "ultimo_mes": meses[-1],
                 "definiciones": {"neto": "crédito bruto del BCB − depósitos del sector en el BCB"}},
        "meses": meses, "series": series,
    })
    registrar("bcb_financiamiento", url=URL, huella=huella(crudo), ultimo_dato=meses[-1])
    u = meses[-1]
    print(f"   BCB {meses[0]}–{u}: crédito neto al sector público {series['total']['neto'][-1]:,.0f} MM Bs "
          f"(Gob. Central {series['gobierno_central']['neto'][-1]:,.0f}; Empresas {series['empresas_publicas']['neto'][-1]:,.0f})")
    verificar_frescura("Financiamiento BCB", dt.date(int(u[:4]), int(u[5:]), 1), max_meses=3)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR financiamiento BCB: {e}")
        sys.exit(1)
