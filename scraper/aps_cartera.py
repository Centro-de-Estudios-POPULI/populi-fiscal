"""
Cartera de inversiones de los Fondos del Sistema Integral de Pensiones (SIP) — APS.

Fuente: APS, Estadísticas › Inversiones del FCI
(https://www.aps.gob.bo/index.php?option=com_sppagebuilder&view=page&id=20). Un PDF por
mes, «Fondos del SIP – Detalle de Cartera», desde 2009. La página arma su lista con una
consulta JSON al propio servidor (`com_ajax … apsfilesdisplayer … getFiles`), carpeta por
carpeta (año › mes): se usa esa misma consulta, sin navegador.

Qué se lee de cada mes: por instrumento y moneda (BOB, USD, UFV, MVDOL), el VALOR NOMINAL,
el VALOR A PRECIO DE MERCADO y el % del fondo, en DÓLARES (así publica la APS).

Trampas que se cuidan:
- Hasta 2023 el PDF trae una página por AFP (Futuro, Previsión) y otra con el consolidado
  «TOTAL AFP»; desde la Gestora, una sola. Se lee SIEMPRE la página consolidada: la que
  tiene un solo encabezado «Valorado a Precio Mcdo.».
- Un gráfico de torta pisa la tabla: sus rótulos usan otro tamaño de letra y quedan a la
  derecha de la última columna. Se descartan por tamaño y por posición.
- Cada número se asigna a la columna cuyo ENCABEZADO le queda más cerca en horizontal, no
  por su orden en la fila (las filas de totales traen columnas vacías).
- Separadores: hasta ~2023 «332,606,239» y «5.27%»; después «8.762.958.455» y «29,82%».
  La convención se detecta en cada archivo.
- Los nombres de archivo cambian de año en año (acentos, guiones, «…2022pdf» sin punto,
  una carpeta «DICIEMBRE» en mayúsculas): se buscan por patrón.
- Control: la suma de los instrumentos tiene que dar el total de cartera del propio PDF.
Salida: data/sip_cartera.json
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import sys
import time

import pdfplumber
import requests

from comun import (DATA, FUENTES, FuenteError, UA, descargar, guardar_json, huella, norm, registrar,
                   verificar_frescura)

PAGINA = "https://www.aps.gob.bo/index.php?option=com_sppagebuilder&view=page&id=20"
API = "https://www.aps.gob.bo/?option=com_ajax&module=apsfilesdisplayer&method=getFiles&format=json&folder="
RAIZ = "webdocs___UNE___DP___Estadisticas___Inversiones+del+FCI"
DESDE = 2017
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE",
         "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
H = {"User-Agent": UA, "X-Requested-With": "XMLHttpRequest", "Referer": PAGINA}
TOL = 0.02   # tolerancia relativa de la suma contra el total del PDF (redondeos por fila)

# Grupo de cada instrumento (por patrón del rótulo, en orden: el primero que calza).
GRUPOS = [
    ("soberanos_exterior", r"SOBERANA"),          # bonos de Bolivia emitidos afuera: DEUDA EXTERNA para el MEFP
    ("tgn_letras", r"LETRAS DEL TESORO"),
    ("tgn_cupones", r"CUPONES DEL TGN"),
    ("tgn_sin_cupones", r"TGN.*SIN CUPONES"),
    ("tgn_obligatorios", r"TGN OBLIGATORIOS"),
    ("tgn_bonos", r"TGN"),
    ("bcb", r"BANCO CENTRAL|BCB"),
    ("dpf", r"DPF"),
    ("bonos_bancarios", r"BONOS BANCARIOS"),
    ("bonos_largo_plazo", r"BONOS A LARGO PLAZO|BONOS PARTICIPATIVOS"),
    ("cuotas_fondos", r"CUOTA"),
    ("titularizacion", r"TITULARIZ"),
    ("pagares", r"PAGAR"),
    ("acciones", r"ACCION"),
    ("exterior_otros", r"CORPORATIVOS|ETF|EXTRANJER"),
    ("bonos_municipales", r"MUNICIPAL"),
]


def listar(folder: str) -> dict:
    for i in range(4):
        try:
            r = requests.get(API + folder, headers=H, timeout=60)
            r.raise_for_status()
            return r.json()["data"]
        except Exception as e:  # noqa: BLE001
            time.sleep(4 * (i + 1))
            ultimo = e
    raise FuenteError(f"la APS no respondió la lista de {folder}: {ultimo}")


def meses_disponibles() -> dict[str, dict]:
    """{'2026-05': {'nombre': …, 'url': …}} para cada mes desde DESDE con Detalle de Cartera."""
    out = {}
    for anio in listar(RAIZ)["folders"]:
        a = anio["name"]
        if not a.isdigit() or int(a) < DESDE:
            continue
        for mes in listar(f"{RAIZ}___{a}")["folders"]:
            nm = norm(mes["name"])
            if nm not in MESES:
                continue
            archivos = listar(f"{RAIZ}___{a}___{mes['name'].replace(' ', '+')}")["files"]
            det = [f for f in archivos if re.search(r"DETALLE\s*DE\s*CARTERA", norm(f["filename"]))]
            if det:
                out[f"{a}-{MESES.index(nm) + 1:02d}"] = {"nombre": det[0]["filename"], "url": det[0]["path"]}
    return out


def a_numero(tok: str, miles: str):
    """Convierte un número de la tabla según la convención del archivo ('.' o ',' de miles)."""
    t = tok.replace("%", "").strip()
    if not re.fullmatch(r"-?[\d.,]+", t):
        return None
    if miles == ",":
        t = t.replace(",", "")
    else:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def convencion(palabras) -> str:
    coma = sum(bool(re.fullmatch(r"\d{1,3}(,\d{3}){2,}", w["text"])) for w in palabras)
    punto = sum(bool(re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", w["text"])) for w in palabras)
    return "," if coma > punto else "."


def unir_partidos(fila: list) -> list:
    """Las filas en negrita parten los números: «29.750.062.864» sale como «2» y
    «9.750.062.864» casi pegados. Dos fragmentos numéricos separados por menos de 1,5 pt
    son el mismo número (entre columnas hay más de 10 pt)."""
    out = []
    for w in fila:
        if (out and re.fullmatch(r"[\d.,]+", out[-1]["text"]) and re.fullmatch(r"[\d.,%]+", w["text"])
                and w["x0"] - out[-1]["x1"] < 1.5):
            out[-1] = {**out[-1], "text": out[-1]["text"] + w["text"], "x1": w["x1"]}
        else:
            out.append(dict(w))
    return out


ES_NUM = re.compile(r"^-?[\d.,]+%?$")


def leer_pdf(ruta) -> dict:
    """Devuelve las filas de la tabla con sus valores POR BLOQUE: un bloque si el PDF trae
    el consolidado (TOTAL AFP o Gestora), dos si sólo trae una tabla por AFP (entonces se
    suman). Tres cuidados: letras duplicadas, filas por tolerancia y columnas por encabezado."""
    paginas = []
    with pdfplumber.open(ruta) as pdf:
        for p in pdf.pages:
            # Algunos PDF dibujan cada letra dos veces (negrita falsa): «BONOS BONOS A A…»
            # y cifras pegadas. dedupe_chars las quita antes de armar palabras.
            ws = p.dedupe_chars(tolerance=1).extract_words(extra_attrs=["size"])
            paginas.append(ws)
    cabeceras = []   # (página, top, [palabras «Valorado»])
    for ip, ws in enumerate(paginas):
        por_fila = collections.defaultdict(list)
        for w in ws:
            if w["text"] == "Valorado":
                por_fila[round(w["top"])].append(w)
        for t in sorted(por_fila):
            cabeceras.append((ip, t, por_fila[t]))
    simples = [c for c in cabeceras if len(c[2]) == 1]
    dobles = [c for c in cabeceras if len(c[2]) == 2]
    if simples:
        ip, top, vals = simples[-1]          # el consolidado: TOTAL AFP o Gestora
    elif dobles:
        ip, top, vals = dobles[0]            # sólo por AFP: se leen las dos y se suman
    else:
        raise FuenteError("no encuentro la fila de encabezados («Valorado a Precio Mcdo.»)")
    ws = paginas[ip]
    val = vals[0]
    tam = val["size"]
    siguientes = [t for (i, t, _) in cabeceras if i == ip and t > top]
    hasta = min(siguientes) - 20 if siguientes else 1e9
    # Encabezados de columna: la fila de «Valorado» (sin «INVERSIONES» ni la «a» suelta).
    cab = sorted((w for w in ws if abs(w["top"] - val["top"]) < 1.5 and abs(w["size"] - tam) < 0.3
                  and w["text"] not in ("INVERSIONES", "IINNVVEERRSSIIOONNEESS", "a")), key=lambda w: w["x0"])
    columnas, bloque, vistos = [], -1, collections.Counter()
    for w in cab:
        if w["text"] == "Valor":             # cada bloque (una AFP, o el total) empieza en «Valor»
            bloque += 1
            vistos = collections.Counter()
        vistos[w["text"]] += 1
        nombre = w["text"] + ("" if vistos[w["text"]] == 1 else str(vistos[w["text"]]))
        columnas.append(((w["x0"] + w["x1"]) / 2, max(bloque, 0), nombre))
    n_bloques = max(b for _, b, _ in columnas) + 1
    borde_der = max(w["x1"] for w in cab) + 12
    miles = convencion(ws)
    # Renglones por tolerancia (no por redondeo): en letra de 3 pt, las cifras de una fila
    # pueden quedar medio punto más abajo que su rótulo.
    tabla = sorted((w for w in ws if abs(w["size"] - tam) < 0.3 and val["top"] + 3 < w["top"] < hasta
                    and w["x1"] <= borde_der), key=lambda w: (w["top"], w["x0"]))
    lineas, tol = [], 0.45 * tam
    for w in tabla:
        if lineas and abs(w["top"] - lineas[-1][0]) <= tol:
            lineas[-1][1].append(w)
        else:
            lineas.append([w["top"], [w]])
    salida = []
    for _, palabras in lineas:
        fila = unir_partidos(sorted(palabras, key=lambda w: w["x0"]))
        rotulo = " ".join(w["text"] for w in fila if not ES_NUM.match(w["text"]))
        if not rotulo:
            continue
        if norm(rotulo).startswith("FUENTE"):   # debajo sólo hay notas al pie
            break
        valores = [dict() for _ in range(n_bloques)]
        for w in fila:
            if not ES_NUM.match(w["text"]):
                continue
            v = a_numero(w["text"], miles)
            if v is None:
                continue
            cx = (w["x0"] + w["x1"]) / 2
            _, b, col = min(columnas, key=lambda c: abs(c[0] - cx))
            valores[b][col] = v
        salida.append({"rotulo": rotulo.strip(), "valores": valores})
    return {"filas": salida, "miles": miles, "bloques": n_bloques,
            "columnas": sorted({c for _, _, c in columnas}, key=[c for _, _, c in columnas].index)}


def clasificar(rotulo: str):
    m = re.search(r"\((BOB|USD|UFV|MVDOL)\)\s*$", rotulo.strip(), re.I)
    moneda = m.group(1).upper() if m else None
    r = norm(rotulo)
    grupo = next((g for g, pat in GRUPOS if re.search(pat, r)), "otros")
    return grupo, moneda


def procesar(ruta) -> dict:
    t = leer_pdf(ruta)
    suma = lambda f, col: (None if all(v.get(col) is None for v in f["valores"])
                           else sum(v.get(col) or 0.0 for v in f["valores"]))
    instrumentos, totales = [], {}
    for f in t["filas"]:
        r = norm(f["rotulo"])
        nom, mer = suma(f, "Valor"), suma(f, "Valorado")
        # El % del fondo sólo es directo con un bloque; con dos AFP se recalcula al final.
        pct = f["valores"][0].get("Porcentaje") if t["bloques"] == 1 else None
        if r.startswith(("TOTAL", "VALOR DE LOS FONDOS", "RECURSOS DE ALTA LIQUIDEZ")):
            clave = ("valor_fondos" if r.startswith("VALOR DE LOS FONDOS") else
                     "liquidez" if r.startswith("RECURSOS") else
                     "cartera_extranjero" if "EXTRANJERO" in r else
                     "cartera_local" if "LOCAL" in r else "cartera")
            totales[clave] = {"nominal": nom, "mercado": mer, "pct": pct}
            continue
        if r.startswith(("CARTERA DE LOS FONDOS", "INVERSIONES", "NOMINAL", "FUENTE", "NOTAS", "1.", "*"))                 or (nom is None and mer is None):
            continue
        grupo, moneda = clasificar(f["rotulo"])
        instrumentos.append({"rotulo": f["rotulo"], "grupo": grupo, "moneda": moneda,
                             "nominal": nom or 0.0, "mercado": mer or 0.0, "pct": pct})
    # Algunos meses (2023) traen el TOTAL del mercado extranjero pero no la fila de su
    # instrumento: la diferencia entra como «sin detalle», en su propio grupo, sin suponer qué es.
    ext = (totales.get("cartera_extranjero") or {})
    if ext.get("mercado"):
        cap = sum(i["mercado"] for i in instrumentos if i["grupo"] in ("soberanos_exterior", "exterior_otros"))
        falta_m = ext["mercado"] - cap
        if falta_m > 0.005 * ext["mercado"]:
            falta_n = (ext.get("nominal") or 0) - sum(i["nominal"] for i in instrumentos
                                                      if i["grupo"] in ("soberanos_exterior", "exterior_otros"))
            instrumentos.append({"rotulo": "Mercado extranjero (sin detalle en el PDF)", "grupo": "exterior_sin_detalle",
                                 "moneda": None, "nominal": max(falta_n, 0.0), "mercado": falta_m, "pct": ext.get("pct")})
    vf = (totales.get("valor_fondos") or {}).get("mercado")
    for i in instrumentos:
        if i["pct"] is None and vf:
            i["pct"] = round(100 * i["mercado"] / vf, 2)
    return {"instrumentos": instrumentos, "totales": totales, "miles": t["miles"],
            "bloques": t["bloques"], "columnas": t["columnas"]}


def validar(mes: str, p: dict) -> list[str]:
    err = []
    tot = p["totales"].get("cartera", {}).get("mercado")
    if not tot:
        return [f"{mes}: no encuentro el total de la cartera"]
    s = sum(i["mercado"] for i in p["instrumentos"])
    if abs(s - tot) > TOL * tot:
        err.append(f"{mes}: la suma de instrumentos ({s:,.0f}) no da el total de cartera ({tot:,.0f})")
    return err


BS_TESTIGO = 4_567_357_000   # nominal en Bs del bono del TGN sin cupones (BOB): igual todos los meses


def compactar(p: dict, rotulos: list) -> dict:
    """Forma publicada de un mes: rótulos por índice, sin filas en cero, dólares enteros.
    El tipo de cambio que usó la APS se mide con el bono TESTIGO: su nominal en Bs es fijo
    (Bs 4.567.357.000), así que su valor en dólares delata la tasa (6,86 hasta hoy). Si la
    APS cambia de tasa (fin del tipo fijo en jun-2026), el testigo lo muestra."""
    filas = []
    for i in p["instrumentos"]:
        if not i["nominal"] and not i["mercado"]:
            continue
        if i["rotulo"] not in rotulos:
            rotulos.append(i["rotulo"])
        filas.append([rotulos.index(i["rotulo"]), i["grupo"], i["moneda"], round(i["nominal"]), round(i["mercado"])])
    testigo = next((i["nominal"] for i in p["instrumentos"]
                    if i["grupo"] == "tgn_sin_cupones" and i["moneda"] == "BOB" and i["nominal"]), None)
    return {"tc_implicito": round(BS_TESTIGO / testigo, 4) if testigo else None,
            "totales": {k: {"nominal": round(v["nominal"] or 0), "mercado": round(v["mercado"] or 0)}
                        for k, v in p["totales"].items()},
            "i": filas}


def main() -> int:
    ruta_json = DATA / "sip_cartera.json"   # el publicado es también la memoria del incremental
    previo = json.loads(ruta_json.read_text(encoding="utf-8")) if ruta_json.exists() else {}
    rotulos = list(previo.get("rotulos", []))
    meses = dict(previo.get("meses", {}))
    sin_lectura = dict(previo.get("meta", {}).get("sin_lectura", {}))
    disponibles = meses_disponibles()
    if not disponibles:
        raise FuenteError("la APS no lista ningún Detalle de Cartera")
    # Se bajan los meses que faltan (salvo los ya declarados ilegibles) y siempre los dos
    # últimos, por si la APS los corrige.
    rehacer = sorted({m for m in disponibles if m not in meses and m not in sin_lectura}
                     | set(sorted(disponibles)[-2:]))
    errores = []
    for mes in rehacer:
        d = disponibles[mes]
        ruta = FUENTES / "aps" / f"{mes}.pdf"
        if ruta.exists() and mes not in sorted(disponibles)[-2:]:
            crudo = ruta.read_bytes()          # ya bajado en esta máquina
        else:
            crudo = descargar(d["url"].replace(" ", "%20"), ruta)
            time.sleep(0.4)
        try:
            p = procesar(ruta)
        except FuenteError as ex:
            errores.append((mes, f"{d['nombre']}: {ex}"))
            continue
        e = validar(mes, p)
        if e:
            errores.append((mes, e[0]))
            continue
        meses[mes] = {"archivo": d["nombre"], "url": d["url"], "huella": huella(crudo), **compactar(p, rotulos)}
        sin_lectura.pop(mes, None)
    # Un mes que no se puede leer o que no suma NO se publica ni se interpola: queda
    # declarado como hueco. Sólo es alarma si falla uno de los tres últimos (formato nuevo).
    for mes, e in errores:
        print(f"    · sin lectura {mes}: {e}")
        sin_lectura[mes] = e
    tcs = sorted({v["tc_implicito"] for v in meses.values() if v.get("tc_implicito")})
    guardar_json("sip_cartera.json", {
        "meta": {"indicador": "Cartera de inversiones de los Fondos del SIP, por instrumento y moneda",
                 "unidad": "dólares (así publica la APS)", "fuente": "Autoridad de Fiscalización y Control de Pensiones y Seguros (APS)",
                 "pagina": PAGINA, "ultimo_mes": max(meses), "tipos_de_cambio_implicitos": tcs,
                 "sin_lectura": dict(sorted(sin_lectura.items())),
                 "columnas_i": ["rotulo", "grupo", "moneda", "nominal_usd", "mercado_usd"],
                 "notas": {"valuacion": "nominal = valor nominal; mercado = valorado a precio de mercado",
                           "huecos": "los meses de «sin_lectura» no se publican ni se interpolan (PDF escaneado o ilegible)",
                           "conversion": "la APS expresa todo en dólares; para volver a bolivianos se usa el MISMO tipo de cambio que usó la APS (tc_implicito, medido con el bono testigo)"}},
        "rotulos": rotulos,
        "meses": dict(sorted(meses.items())),
    })
    registrar("sip_cartera", pagina=PAGINA, ultimo_dato=max(meses), meses=len(meses), sin_lectura=len(sin_lectura))
    u = meses[max(meses)]
    tgn = sum(f[4] for f in u["i"] if f[1].startswith("tgn"))
    print(f"   SIP {min(meses)}–{max(meses)} ({len(meses)} meses, {len(sin_lectura)} sin lectura); {max(meses)}: "
          f"cartera US$ {u['totales']['cartera']['mercado']/1e6:,.0f} MM, TGN (mercado) US$ {tgn/1e6:,.0f} MM; "
          f"tipos de cambio implícitos de la APS: {tcs}")
    verificar_frescura("Cartera SIP", dt.date(int(max(meses)[:4]), int(max(meses)[5:]), 1), max_meses=5)
    recientes = sorted(disponibles)[-3:]
    if any(m in sin_lectura for m in recientes):
        raise FuenteError(f"no se pudo leer un mes reciente: {[m for m in recientes if m in sin_lectura]} (¿cambió el formato?)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:   # prueba: python aps_cartera.py archivo.pdf
        p = procesar(sys.argv[1])
        print(json.dumps({"miles": p["miles"], "columnas": p["columnas"], "totales": p["totales"]}, ensure_ascii=False))
        for i in p["instrumentos"]:
            print(f"  {i['grupo']:18s} {str(i['moneda']):6s} nom {i['nominal']:>16,.0f} mer {i['mercado']:>16,.0f} {i['pct'] or 0:6.2f}  {i['rotulo'][:60]}")
        print("control:", validar("prueba", p) or "suma OK")
        sys.exit(0)
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR cartera SIP: {e}")
        sys.exit(1)
