"""
PIB nominal (a precios corrientes), año de referencia 2017 — el denominador de todos
los ratios del monitor.

Fuente: INE, «Producto Interno Bruto trimestral, año de referencia 2017»
(https://www.ine.gob.bo/referencia2017/pib_trimestral.html), cuadro «PIB por grupos
de actividad económica según trimestre», en millones de bolivianos corrientes.

¿Por qué desde 2017? El INE cambió el año base de las cuentas nacionales (1990 → 2017)
y el nivel del PIB nominal saltó (2017: 259 mil millones en la base vieja, 317 mil
en la nueva). Mezclar bases cambia cualquier ratio sobre el PIB sin que la política
fiscal haya cambiado nada. El monitor usa SÓLO la base 2017.

El enlace se busca por el TÍTULO del cuadro en la página del INE (la nube del INE
cambia los identificadores de descarga cuando actualiza).
Salida: data/pib.json
"""
from __future__ import annotations

import html
import re
import sys

import openpyxl

from comun import (FUENTES, FuenteError, descargar, guardar_json, huella, norm, num,
                   registrar, verificar_frescura)
import datetime as dt

PAGINA = "https://www.ine.gob.bo/referencia2017/pib_trimestral.html"
TITULO = "PRODUCTO INTERNO BRUTO POR GRUPOS DE ACTIVIDAD ECONOMICA SEGUN TRIMESTRE"


def enlace_del_cuadro() -> str:
    pag = descargar(PAGINA, FUENTES / "ine_pib" / "_pagina.html").decode("utf-8", "ignore")
    for href, texto in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', pag, re.S):
        t = norm(html.unescape(re.sub(r"<[^>]+>", " ", texto)))
        # El título exacto; se descartan «ESTRUCTURA DEL…», «VOLUMEN…», «VALOR AGREGADO…»
        if t.startswith("BOLIVIA: " + TITULO):
            return href if href.startswith("http") else "https://www.ine.gob.bo/referencia2017/" + href
    raise FuenteError("no encuentro en la página del INE el cuadro del PIB nominal por trimestre")


def leer(ruta) -> list[dict]:
    ws = openpyxl.load_workbook(ruta, read_only=True, data_only=True).worksheets[0]
    filas = [f for f in ws.iter_rows(values_only=True)]
    no_vacias = [f for f in filas if f and any(isinstance(c, str) and c.strip() for c in f)][:4]
    titulo = " ".join(norm(c) for f in no_vacias for c in f if isinstance(c, str))
    # El de volumen dice «millones de bolivianos ENCADENADOS»; el de estructura, «porcentaje».
    if ("MILLONES DE BOLIVIANOS" not in titulo or any(x in titulo for x in ("ENCADENAD", "VOLUMEN", "ESTRUCTURA"))):
        raise FuenteError(f"el cuadro bajado no es el PIB nominal en millones: «{titulo[:120]}»")
    i_anio = next(i for i, f in enumerate(filas) if f and sum(bool(re.match(r"^\d{4}", str(c or "").strip())) for c in f) >= 5)
    anios, anio, prelim = {}, None, {}
    for j, c in enumerate(filas[i_anio]):
        m = re.match(r"^(\d{4})\s*(\(p\))?", str(c or "").strip())
        if m:
            anio = int(m.group(1)); prelim[anio] = bool(m.group(2))
        anios[j] = anio
    trim = {j: str(c).strip() for j, c in enumerate(filas[i_anio + 1]) if c}
    rotulo = lambda f: next((norm(c) for c in f if isinstance(c, str) and c.strip()), "")
    fila_pib = next((f for f in filas if f and rotulo(f).startswith("PRODUCTO INTERNO BRUTO")), None)
    if fila_pib is None:
        raise FuenteError("no encuentro la fila «PRODUCTO INTERNO BRUTO»")
    romanos = {"I": 1, "II": 2, "III": 3, "IV": 4}
    out = []
    for j, t in trim.items():
        v = num(fila_pib[j])
        if v is None or t not in romanos or anios.get(j) is None:
            continue
        out.append({"periodo": f"{anios[j]}-T{romanos[t]}", "anio": anios[j], "trimestre": romanos[t],
                    "pib": round(v, 1), "preliminar": prelim[anios[j]]})
    return out


def main() -> int:
    url = enlace_del_cuadro()
    ruta = FUENTES / "ine_pib" / "pib_corrientes.xlsx"
    crudo = descargar(url, ruta)
    trim = leer(ruta)
    if not trim or trim[0]["periodo"] != "2017-T1":
        raise FuenteError(f"la serie debería empezar en 2017-T1 y empieza en {trim[0]['periodo'] if trim else '—'}")
    # Continuidad: ningún trimestre salteado.
    for a, b in zip(trim, trim[1:]):
        if (b["anio"] * 4 + b["trimestre"]) - (a["anio"] * 4 + a["trimestre"]) != 1:
            raise FuenteError(f"hueco en la serie del PIB entre {a['periodo']} y {b['periodo']}")
    anual = {}
    for t in trim:
        anual.setdefault(t["anio"], []).append(t)
    anual = [{"anio": a, "pib": round(sum(x["pib"] for x in ts), 1), "preliminar": ts[0]["preliminar"]}
             for a, ts in anual.items() if len(ts) == 4]
    guardar_json("pib.json", {
        "meta": {"indicador": "Producto Interno Bruto a precios corrientes",
                 "unidad": "millones de bolivianos", "base": "año de referencia 2017",
                 "fuente": "Instituto Nacional de Estadística (INE)", "url": url, "pagina": PAGINA,
                 "ultimo_trimestre": trim[-1]["periodo"]},
        "trimestral": trim, "anual": anual,
    })
    registrar("pib", url=url, huella=huella(crudo), ultimo_dato=trim[-1]["periodo"])
    print(f"   PIB {trim[0]['periodo']}–{trim[-1]['periodo']}; " +
          ", ".join(f"{a['anio']}: {a['pib']:,.0f}" for a in anual[-3:]))
    # Trimestral con ~3 meses de rezago de publicación: más de 9 meses sin trimestre nuevo es anomalía.
    t = trim[-1]
    verificar_frescura("PIB", dt.date(t["anio"], t["trimestre"] * 3, 1), max_meses=9)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR PIB: {e}")
        sys.exit(1)
