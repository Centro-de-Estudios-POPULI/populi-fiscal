"""
Deuda pública interna del Tesoro General de la Nación (TGN), por tenedor e instrumento.

Fuente: MEFP, Viceministerio del Tesoro y Crédito Público
(https://www.economiayfinanzas.gob.bo/viceministerios/vtcp/deuda-interna-tgn), hoja
«Saldo» de cada archivo, en millones de bolivianos.
Dos formatos:
- desde 2026, un archivo por mes (`…DEUDA_INTERNA_BS_<MES>.xlsx`) con todo el TGN;
- 2023–2025, dos archivos de cierre por año, «…CON EL SECTOR PUBLICO_BS_DICIEMBRE» y
  «…CON EL SECTOR PRIVADO_BS_DICIEMBRE».
Cada hoja «Saldo» trae diciembre del año anterior + los meses del año ⇒ serie mensual
desde diciembre de 2022. Lo anterior a 2022 NO está en la página del MEFP.

Trampas que se cuidan:
- Los meses que todavía no pasaron vienen con 0, no vacíos: se cortan en el mes del
  archivo. Si no, la deuda «cae a cero» en agosto.
- Los rótulos se repiten en distintos tenedores («Fondos», «BTs-Neg.», «BTs-No Neg.»):
  se leen dentro de su jerarquía sector → tenedor → instrumento, y se verifica que
  cada nivel sume el de arriba.
- «AFPs (Pensiones)» es la línea de los viejos Bonos AFP y hoy está en cero: lo que los
  fondos de pensiones compran en subasta queda dentro de «Mercado financiero (Subasta)»,
  sin identificar al comprador. El MEFP no dice cuánto de eso es de los fondos.
Salida: data/deuda_interna.json
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from urllib.parse import unquote

import openpyxl

from comun import (FUENTES, FuenteError, descargar, guardar_json, huella, norm, num,
                   registrar, verificar_frescura)

PAGINA = "https://www.economiayfinanzas.gob.bo/viceministerios/vtcp/deuda-interna-tgn?title=&field_fecha_value=&page={}"
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE",
         "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
MES_CORTO = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8,
             "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12}
TOL = 0.2   # millones de Bs

# Jerarquía: sector → tenedor → instrumento. Los rótulos se normalizan con norm().
SECTORES = {"SECTOR PUBLICO FINANCIERO": "publico_financiero",
            "SECTOR PUBLICO NO FINANCIERO": "publico_no_financiero",
            "SECTOR PRIVADO": "privado"}
TENEDORES = {
    "publico_financiero": {"BCB": "bcb", "FONDOS": "fondos"},
    "publico_no_financiero": {"OTROS PUBLICOS": "otros_publicos"},
    "privado": {"AFPS (PENSIONES)": "afps", "AFPS": "afps", "MERCADO FINANCIERO (SUBASTA)": "mercado_financiero",
                "OTROS PRIVADOS": "otros_privados", "FONDOS": "fondos", "TESORO DIRECTO": "tesoro_directo"},
}
INSTRUMENTOS = {
    "BTS-CRED.EMERG.": "bt_credito_emergencia", "BTS-NEG.": "bt_negociables", "BTS-NO NEG.": "bt_no_negociables",
    "DEUDA HIST. LT \"A\"": "deuda_historica_a", "DEUDA HIST-LT \"A\"": "deuda_historica_a",
    "DEUDA HIST-LT \"B\"": "deuda_historica_b", "DEUDA HIST. LT \"B\"": "deuda_historica_b",
    "TITULOS-BCB": "titulos_bcb", "BTS-FDOS. NEG.": "bt_negociables", "BTS-FDOS. NO NEG.": "bt_no_negociables",
    "BONOS-AFPS": "bonos_afp", "BONOS \"C\"": "bonos_c", "LETRAS \"C\"": "letras_c",
    "BONOS PRIVADOS": "bonos_privados", "BTS-EXTRABURSATIL": "bt_extrabursatil",
    # Erratas de la fuente, aceptadas UNA por UNA (un rótulo nuevo desconocido detiene todo):
    "BTTS-NEG.": "bt_negociables",          # 2024, sector privado
}
NOMBRES = {
    "publico_financiero": "Sector público financiero", "publico_no_financiero": "Sector público no financiero",
    "privado": "Sector privado", "bcb": "Banco Central de Bolivia", "fondos": "Fondos",
    "otros_publicos": "Otros públicos", "afps": "AFP (Bonos AFP)", "mercado_financiero": "Mercado financiero (subasta)",
    "otros_privados": "Otros privados", "tesoro_directo": "Tesoro Directo",
    "bt_credito_emergencia": "Bonos del Tesoro — crédito de emergencia", "bt_negociables": "Bonos del Tesoro negociables",
    "bt_no_negociables": "Bonos del Tesoro no negociables", "deuda_historica_a": "Deuda histórica, Letra «A»",
    "deuda_historica_b": "Deuda histórica, Letra «B»", "titulos_bcb": "Títulos BCB", "bonos_afp": "Bonos AFP",
    "bonos_c": "Bonos «C» (subasta)", "letras_c": "Letras «C» (subasta)", "bonos_privados": "Bonos privados",
    "bt_extrabursatil": "Bonos del Tesoro extrabursátiles",
}


def enlaces() -> list[dict]:
    """Recorre las páginas del listado y clasifica cada Excel en bolivianos."""
    vistos, out = set(), []
    for p in range(0, 8):
        html = descargar(PAGINA.format(p), FUENTES / "mefp_deuda_interna" / f"_pagina{p}.html").decode("utf-8", "ignore")
        nuevos = 0
        for href in re.findall(r'href="([^"]+\.xlsx)"', html):
            url = href if href.startswith("http") else "https://www.economiayfinanzas.gob.bo" + href
            if url in vistos:
                continue
            vistos.add(url)
            nombre = norm(unquote(url.split("/")[-1]).replace("_", " "))
            if not re.search(r"\bBS\b", nombre):
                continue   # la versión «MO» (moneda de origen) no se usa
            anio = re.search(r"(20\d{2})", nombre)
            mes = next((i + 1 for i, m in enumerate(MESES) if m in nombre), None)
            if not anio or not mes:
                continue
            tipo = "publico" if "SECTOR PUBLICO" in nombre else "privado" if "SECTOR PRIVADO" in nombre else "total"
            out.append({"url": url, "anio": int(anio.group(1)), "mes": mes, "tipo": tipo,
                        "carpeta": re.search(r"files/(\d{4}-\d{2})/", url).group(1) if re.search(r"files/(\d{4}-\d{2})/", url) else ""})
            nuevos += 1
        if not nuevos:
            break
    return out


def elegir(archivos: list[dict]) -> list[dict]:
    """Por año, el archivo del ÚLTIMO mes (y dentro de ese mes, el subido más tarde).
    Para los años de formato viejo se necesitan los dos: público y privado."""
    elegidos = []
    for anio in sorted({a["anio"] for a in archivos}):
        del_anio = [a for a in archivos if a["anio"] == anio]
        mes = max(a["mes"] for a in del_anio)
        del_mes = [a for a in del_anio if a["mes"] == mes]
        tipos = {a["tipo"] for a in del_mes}
        if "total" in tipos:
            elegidos.append(max((a for a in del_mes if a["tipo"] == "total"), key=lambda a: a["carpeta"]))
        elif {"publico", "privado"} <= tipos:
            for t in ("publico", "privado"):
                elegidos.append(max((a for a in del_mes if a["tipo"] == t), key=lambda a: a["carpeta"]))
        else:
            raise FuenteError(f"{anio}: falta el archivo {({'publico', 'privado'} - tipos)} del cierre")
    return elegidos


def leer_saldo(ruta, anio: int, mes_corte: int, avisos: list) -> dict[str, dict[str, float]]:
    wb = openpyxl.load_workbook(ruta, data_only=True)
    ws = next((w for w in wb.worksheets if norm(w.title) == "SALDO"), None)
    if ws is None:
        raise FuenteError(f"{ruta.name}: no tiene hoja «Saldo»")
    filas = list(ws.iter_rows(values_only=True))
    h = next((i for i, f in enumerate(filas) if f and norm(f[0]) == "DETALLE"), None)
    if h is None:
        raise FuenteError(f"{ruta.name}: no encuentro la fila «Detalle»")
    # El año del cuadro lo da su TÍTULO («2023(p)»), no el rótulo de la primera columna:
    # el archivo de 2023 del sector privado rotula «Dic-24» la columna de diciembre de 2022.
    # (la celda del año puede venir como texto «2023(p)» o como número 2023)
    titulo = next((norm(c) for f in filas[:h] for c in f
                   if c is not None and re.fullmatch(r"\d{4}", norm(c).replace(".0", ""))), "")
    if not titulo.startswith(str(anio)):
        raise FuenteError(f"{ruta.name}: el título dice «{titulo}» y el archivo es de {anio}")
    col = {}
    for j, c in enumerate(filas[h]):
        t = norm(c)
        m = re.match(r"^DIC-(\d{2})$", t)
        if m:
            if 2000 + int(m.group(1)) != anio - 1:
                avisos.append(f"{ruta.name}: la columna de diciembre del año anterior dice «{str(c).strip()}»; "
                              f"se lee como dic-{anio - 1} (el cuadro es de {anio})")
            col[j] = f"{anio - 1}-12"
        elif t[:3] in MES_CORTO and len(t) <= 4:
            mm = MES_CORTO[t[:3]]
            if mm <= mes_corte:           # los meses por venir traen 0: se descartan
                col[j] = f"{anio}-{mm:02d}"
    if f"{anio - 1}-12" not in col.values():
        raise FuenteError(f"{ruta.name}: falta la columna de diciembre del año anterior")
    datos: dict[str, dict[str, float]] = {}
    sector = tenedor = None
    for f in filas[h + 1:]:
        if not f or not isinstance(f[0], str) or not f[0].strip():
            continue
        r = norm(f[0])
        if r.startswith(("(P)", "PRELIMINAR", "NOTA", "FUENTE", "ELABORACION", "CIERRE")):
            break
        valores = {m: num(f[j]) for j, m in col.items()}
        if r in ("DEUDA PUBLICA INTERNA TOTAL", "DEUDA PUBLICA INTERNA TOTAL DEL TGN", "SECTOR PUBLICO"):
            datos.setdefault("total_archivo", valores)
            continue
        if r in SECTORES:
            sector, tenedor = SECTORES[r], None
            datos[sector] = valores
            continue
        if sector and r in TENEDORES[sector]:
            tenedor = TENEDORES[sector][r]
            datos[f"{sector}.{tenedor}"] = valores
            continue
        if sector and tenedor and r in INSTRUMENTOS:
            datos[f"{sector}.{tenedor}.{INSTRUMENTOS[r]}"] = valores
            continue
        raise FuenteError(f"{ruta.name}: rótulo desconocido «{f[0].strip()}» (sector={sector}, tenedor={tenedor})")
    return datos


def main() -> int:
    elegidos = elegir(enlaces())
    serie: dict[str, dict[str, float]] = {}
    procedencia, avisos, empalmes = [], [], []
    for a in elegidos:
        nombre = unquote(a["url"].split("/")[-1])
        ruta = FUENTES / "mefp_deuda_interna" / nombre.replace(" ", "_")
        crudo = descargar(a["url"], ruta)
        procedencia.append({"url": a["url"], "huella": huella(crudo), "mes": f"{a['anio']}-{a['mes']:02d}"})
        datos = leer_saldo(ruta, a["anio"], a["mes"], avisos)
        for clave, valores in datos.items():
            if clave == "total_archivo":
                continue
            for m, v in valores.items():
                # El diciembre del año anterior se repite en el archivo siguiente: tiene que
                # coincidir con el cierre del archivo previo (control de empalme).
                previo = serie.get(clave, {}).get(m)
                if previo is not None and v is not None and abs(previo - v) > TOL:
                    empalmes.append(f"{clave} {m}: {previo:,.1f} (cierre) vs {v:,.1f} (apertura del año siguiente)")
                serie.setdefault(clave, {})[m] = v
    for x in avisos:
        print("   aviso de la fuente:", x)
    if empalmes:
        for e in empalmes[:10]:
            print("    · empalme:", e)
        raise FuenteError(f"{len(empalmes)} saldos de diciembre no coinciden entre un año y el siguiente")
    meses = sorted({m for v in serie.values() for m in v})
    # Controles: instrumentos → tenedor → sector → total (total = suma de los tres sectores).
    errores = []
    for m in meses:
        for clave in list(serie):
            partes = [k for k in serie if k.startswith(clave + ".") and k.count(".") == clave.count(".") + 1]
            if partes:
                a = serie[clave].get(m)
                b = sum(serie[k].get(m) or 0 for k in partes)
                if a is None or abs(a - b) > TOL:
                    errores.append(f"{m} {clave}: {a} ≠ suma {b:,.1f}")
    if errores:
        for e in errores[:20]:
            print("    ·", e)
        raise FuenteError(f"{len(errores)} niveles de la deuda interna no suman")
    total = [round(sum(serie[s].get(m) or 0 for s in SECTORES.values()), 1) for m in meses]
    salida = {k: [None if v.get(m) is None else round(v[m], 1) for m in meses] for k, v in sorted(serie.items())}
    ult = meses[-1]
    guardar_json("deuda_interna.json", {
        "meta": {"indicador": "Deuda pública interna del TGN, por tenedor e instrumento (saldo a fin de mes)",
                 "unidad": "millones de bolivianos", "fuente": "Ministerio de Economía y Finanzas Públicas (MEFP), VTCP",
                 "pagina": PAGINA.format(0), "ultimo_mes": ult, "nombres": NOMBRES,
                 "notas": {"afps": "«AFPs» son los Bonos AFP de la reforma de 1997 (hoy en cero). Los bonos que los fondos "
                                   "de pensiones compran en subasta están dentro de «Mercado financiero (subasta)», sin "
                                   "separar al comprador.",
                           "cobertura": "La página del MEFP publica esta serie desde diciembre de 2022."},
                 "archivos": procedencia, "avisos_fuente": avisos},
        "meses": meses, "total": total, "series": salida,
    })
    registrar("deuda_interna", pagina=PAGINA.format(0), ultimo_dato=ult, archivos=len(procedencia))
    i = meses.index(ult)
    print(f"   deuda interna TGN {meses[0]}–{ult}: {total[i]:,.0f} MM Bs "
          f"(BCB {salida['publico_financiero.bcb'][i]:,.0f}; privado {salida['privado'][i]:,.0f})")
    verificar_frescura("Deuda interna TGN", dt.date(int(ult[:4]), int(ult[5:]), 1), max_meses=4)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR deuda interna: {e}")
        sys.exit(1)
