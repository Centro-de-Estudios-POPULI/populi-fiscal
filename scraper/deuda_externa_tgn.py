"""
Deuda pública externa del TGN por acreedor — MEFP.

Fuente: MEFP, VTCP, «Deuda Pública del TGN Externa»
(https://www.economiayfinanzas.gob.bo/viceministerios/vtcp/deuda-externa-tgn), hoja
«SALDO» («2.Saldo» en 2021), en millones de dólares. Cierres de diciembre (2021–2025)
+ un archivo por mes del año en curso; cada uno trae diciembre del año anterior + sus
meses ⇒ serie mensual desde diciembre de 2020.

Complementa al BCB: el BCB agrupa a China dentro de «otros bilaterales»; el MEFP la
muestra acreedor por acreedor.

Controles: cada grupo (multilateral, bilateral, privados) suma sus acreedores; el total
suma los grupos; el diciembre de cada archivo coincide con la apertura del siguiente;
los meses por venir (que vienen en 0) se descartan. Los nombres de los acreedores
cambian entre años («Asociación Internacional para el Desarrollo» / «de Fomento»): la
clave sale de un patrón del nombre, así la serie de cada acreedor no se parte.
Salida: data/deuda_externa_tgn.json
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
from urllib.parse import unquote

import openpyxl

from comun import (FUENTES, FuenteError, descargar, guardar_json, huella, norm, num,
                   registrar, verificar_frescura)

PAGINA = "https://www.economiayfinanzas.gob.bo/viceministerios/vtcp/deuda-externa-tgn?page={}"
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE",
         "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
MES_CORTO = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8,
             "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12}
GRUPOS = {"MULTILATERAL": "multilateral", "BILATERAL": "bilateral", "PRIVADOS": "privados"}
TOL = 0.2
# La clave de cada acreedor sale de un PATRÓN de su nombre. Uno que no calce con
# ninguno entra igual, con su nombre, y deja un aviso.
ACREEDORES = [
    ("EUROPEO DE INVERSI", "bei"), ("INTERAMERICANO DE DESARROLLO", "bid"),
    ("RECONSTRUCCION Y FOMENTO", "birf"), ("ANDINA DE FOMENTO", "caf"),
    ("DESARROLLO DE AMERICA LATINA", "caf"), ("DESARROLLO AGRICOLA", "fida"), ("NORDICO", "fnd"),
    ("CUENCA DEL PLATA", "fonplata"), ("FONPLATA", "fonplata"), ("ASOCIACION INTERNACIONAL", "aif"),
    ("PETROLEO", "opep"), ("OFID", "opep"), ("ITALIA", "italia"), ("NACION ARGENTINA", "argentina"),
    ("BRASIL", "brasil"), ("CHINA", "china"), ("JAPON", "japon"), ("COREA", "corea"),
    ("VENEZUELA", "venezuela"), ("ESPANA", "espana"), ("ALEMANIA", "alemania"), ("FRANCIA", "francia"),
    ("BONOS SOBERANOS", "bonos_soberanos"),
]
NOMBRE_CORTO = {"bei": "Banco Europeo de Inversiones", "bid": "BID", "birf": "Banco Mundial (BIRF)",
                "caf": "CAF", "fida": "FIDA", "fnd": "Fondo Nórdico", "fonplata": "FONPLATA",
                "aif": "Banco Mundial (AIF)", "opep": "OFID (OPEP)", "italia": "Italia",
                "argentina": "Banco de la Nación Argentina", "brasil": "Brasil", "china": "China",
                "japon": "Japón", "corea": "Corea", "venezuela": "Venezuela", "espana": "España",
                "alemania": "Alemania", "francia": "Francia", "bonos_soberanos": "Bonos soberanos"}


def clave_acreedor(txt: str, avisos: list) -> str:
    n = norm(txt)
    for patron, clave in ACREEDORES:
        if patron in n:
            return clave
    s = unicodedata.normalize("NFKD", txt)
    s = re.sub(r"[^a-z0-9]+", "_", "".join(c for c in s if not unicodedata.combining(c)).lower()).strip("_")
    avisos.append(f"acreedor nuevo sin clave conocida: «{txt}» (se usa «{s}»)")
    return s


def enlaces() -> list[dict]:
    vistos, out = set(), []
    for p in range(0, 6):
        html = descargar(PAGINA.format(p), FUENTES / "mefp_deuda_externa" / f"_pagina{p}.html").decode("utf-8", "ignore")
        nuevos = 0
        for href in re.findall(r'href="([^"]+\.xlsx)"', html):
            url = href if href.startswith("http") else "https://www.economiayfinanzas.gob.bo" + href
            if url in vistos:
                continue
            vistos.add(url)
            nombre = norm(unquote(url.split("/")[-1]).replace("_", " "))
            anio = re.search(r"(20\d{2})", nombre)
            mes = next((i + 1 for i, m in enumerate(MESES) if m in nombre), None)
            if anio and mes:
                carpeta = re.search(r"files/(\d{4}-\d{2})/", url)
                out.append({"url": url, "anio": int(anio.group(1)), "mes": mes,
                            "carpeta": carpeta.group(1) if carpeta else ""})
                nuevos += 1
        if not nuevos:
            break
    elegidos = []
    for anio in sorted({a["anio"] for a in out}):
        mes = max(a["mes"] for a in out if a["anio"] == anio)
        # dentro del mes, el subido más tarde (hay «ABRIL_2026_0» y «ABRIL_2026_1»)
        elegidos.append(max((a for a in out if a["anio"] == anio and a["mes"] == mes),
                            key=lambda a: (a["carpeta"], a["url"])))
    return elegidos


def leer(ruta, anio: int, mes_corte: int, nombres: dict, avisos: list) -> dict:
    wb = openpyxl.load_workbook(ruta, data_only=True)
    # «SALDO» desde 2022; «2.Saldo» en el cierre de 2021
    ws = next((w for w in wb.worksheets if re.sub(r"^\d+\.\s*", "", norm(w.title)) == "SALDO"), None)
    if ws is None:
        raise FuenteError(f"{ruta.name}: no tiene hoja «SALDO»")
    filas = list(ws.iter_rows(values_only=True))
    h = next((i for i, f in enumerate(filas) if f and norm(f[0]) in ("DETALLE", "NOMBRE DEL ACREEDOR")), None)
    if h is None:
        raise FuenteError(f"{ruta.name}: no encuentro la fila de encabezado («Detalle» / «Nombre del Acreedor»)")
    col = {}
    for j, c in enumerate(filas[h]):
        if isinstance(c, dt.datetime):          # 2021: la apertura viene como fecha
            if (c.year, c.month) != (anio - 1, 12):
                avisos.append(f"{ruta.name}: la columna de apertura es {c:%Y-%m}; se lee como dic-{anio - 1}")
            col[j] = f"{anio - 1}-12"
            continue
        t = norm(c)
        m = re.match(r"^DIC-(\d{2})$", t)
        if m:
            if 2000 + int(m.group(1)) != anio - 1:
                avisos.append(f"{ruta.name}: la columna de apertura dice «{str(c).strip()}»; se lee como dic-{anio - 1}")
            col[j] = f"{anio - 1}-12"
        elif t[:3] in MES_CORTO and (len(t) <= 4 or t in MESES) and MES_CORTO[t[:3]] <= mes_corte:
            col[j] = f"{anio}-{MES_CORTO[t[:3]]:02d}"
    if f"{anio - 1}-12" not in col.values():
        raise FuenteError(f"{ruta.name}: falta la columna de apertura (diciembre de {anio - 1})")
    datos, grupo = {}, None
    for f in filas[h + 1:]:
        if not f or not isinstance(f[0], str) or not f[0].strip():
            continue
        r = norm(f[0])
        if r.startswith(("FUENTE", "ELABORACION", "PRELIMINAR", "(P)", "NOTA", "FECHA DE REPORTE")):
            break
        valores = {m: num(f[j]) for j, m in col.items()}
        if r.startswith(("DEUDA PUBLICA EXTERNA", "TOTAL DEUDA")):
            datos["total"] = valores
        elif r in GRUPOS:
            grupo = GRUPOS[r]
            datos[grupo] = valores
        elif grupo:
            k = clave_acreedor(f[0].strip(), avisos)
            nombres.setdefault(k, NOMBRE_CORTO.get(k, f[0].strip()))
            clave = f"{grupo}.{k}"
            if clave in datos:
                raise FuenteError(f"{ruta.name}: dos filas caen en la misma clave «{clave}»")
            datos[clave] = valores
        else:
            raise FuenteError(f"{ruta.name}: fila «{f[0].strip()}» fuera de todo grupo")
    if "total" not in datos:
        raise FuenteError(f"{ruta.name}: no encuentro el total")
    return datos


def main() -> int:
    serie, nombres, avisos, empalmes, procedencia, revisiones = {}, {}, [], [], [], []
    for a in enlaces():
        nombre = unquote(a["url"].split("/")[-1]).replace(" ", "_")
        ruta = FUENTES / "mefp_deuda_externa" / nombre
        crudo = descargar(a["url"], ruta)
        procedencia.append({"url": a["url"], "huella": huella(crudo), "mes": f"{a['anio']}-{a['mes']:02d}"})
        for clave, valores in leer(ruta, a["anio"], a["mes"], nombres, avisos).items():
            for m, v in valores.items():
                # El diciembre se publica dos veces: como cierre de un año y como apertura del
                # siguiente, ya REVISADO (el revisado coincide con el BCB). Gana el más nuevo y
                # la revisión queda anotada; una diferencia grande delata un error de lectura.
                previo = serie.get(clave, {}).get(m)
                if previo is not None and v is not None and abs(previo - v) > TOL:
                    if abs(previo - v) > max(50, 0.01 * abs(v)):
                        empalmes.append(f"{clave} {m}: {previo:,.1f} vs {v:,.1f}")
                    elif clave == "total":
                        revisiones.append({"mes": m, "publicado": round(previo, 1), "revisado": round(v, 1)})
                serie.setdefault(clave, {})[m] = v
    for x in dict.fromkeys(avisos):
        print("   aviso de la fuente:", x)
    if empalmes:
        for e in empalmes[:10]:
            print("    · empalme:", e)
        raise FuenteError(f"{len(empalmes)} saldos cambian demasiado entre el cierre de un año y la apertura del siguiente")
    for r in revisiones:
        print(f"   revisión del MEFP: total {r['mes']} {r['publicado']:,.1f} → {r['revisado']:,.1f}")
    meses = sorted({m for v in serie.values() for m in v})
    errores = []
    for m in meses:
        for g in GRUPOS.values():
            partes = [k for k in serie if k.startswith(g + ".")]
            a, b = serie.get(g, {}).get(m), sum(serie[k].get(m) or 0 for k in partes)
            if a is not None and abs(a - b) > TOL:
                errores.append(f"{m} {g}: {a} ≠ {b:,.1f}")
        a, b = serie["total"].get(m), sum(serie.get(g, {}).get(m) or 0 for g in GRUPOS.values())
        if a is None or abs(a - b) > TOL:
            errores.append(f"{m} total: {a} ≠ {b:,.1f}")
    if errores:
        for e in errores[:20]:
            print("    ·", e)
        raise FuenteError(f"{len(errores)} sumas no cierran en la deuda externa del TGN")
    salida = {k: [None if v.get(m) is None else round(v[m], 1) for m in meses] for k, v in sorted(serie.items())}
    ult = meses[-1]
    guardar_json("deuda_externa_tgn.json", {
        "meta": {"indicador": "Deuda pública externa del TGN por acreedor (saldo a fin de mes)",
                 "unidad": "millones de dólares", "fuente": "Ministerio de Economía y Finanzas Públicas (MEFP), VTCP",
                 "pagina": PAGINA.format(0), "ultimo_mes": ult, "nombres": nombres,
                 "archivos": procedencia, "avisos_fuente": list(dict.fromkeys(avisos)),
                 "revisiones": revisiones},
        "meses": meses, "series": salida,
    })
    registrar("deuda_externa_tgn", pagina=PAGINA.format(0), ultimo_dato=ult, archivos=len(procedencia))
    top = sorted(((k.split(".")[1], v[-1]) for k, v in salida.items() if k.count(".") == 1 and v[-1]),
                 key=lambda x: -x[1])[:6]
    print(f"   deuda externa TGN {meses[0]}–{ult}: {salida['total'][-1]:,.1f} MM US$; mayores: "
          + ", ".join(f"{nombres.get(k, k)} {v:,.0f}" for k, v in top))
    verificar_frescura("Deuda externa TGN", dt.date(int(ult[:4]), int(ult[5:]), 1), max_meses=4)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR deuda externa TGN: {e}")
        sys.exit(1)
