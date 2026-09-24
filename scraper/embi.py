"""
Riesgo país: spread del EMBI Global Diversified (J.P. Morgan).

Fuente: Banco Central de la República Dominicana, «Serie Histórica Spread del EMBI»
(Entorno Internacional). Es un Excel diario con 19 países y los agregados Global y
Latino, que el BCRD actualiza casi todos los días hábiles.

⚠️ La misma página del BCRD enlaza también `EMBI.xlsx`, un archivo VIEJO que sigue
respondiendo 200 pero quedó clavado en octubre de 2024. Por eso no se elige «el
primero que responda»: se bajan las direcciones conocidas y se queda la que LLEGA
MÁS LEJOS en fecha.

Unidad de la fuente: puntos porcentuales (4,31 = 431 puntos básicos). Se publica en
puntos básicos, que es como se lee el riesgo país.
Salida: data/embi.json
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys

import openpyxl

from comun import (FUENTES, FuenteError, descargar, guardar_json, huella, norm, num,
                   registrar, verificar_frescura)

PAGINA = "https://www.bancentral.gov.do/a/d/2585-entorno-internacional"
API = "https://www.bancentral.gov.do/Home/GetContentForRender"
CANDIDATAS = [
    "https://cdn.bancentral.gov.do/documents/entorno-internacional/documents/Serie_Historica_Spread_del_EMBI.xlsx",
    "https://bcrdgdcprod.blob.core.windows.net/documents/entorno-internacional/documents/Serie_Historica_Spread_del_EMBI.xlsx",
]
# Países que se muestran en la comparación regional (la fuente trae 19).
REGION = ["Argentina", "Bolivia", "Brasil", "Chile", "Colombia", "Ecuador", "El Salvador",
          "México", "Paraguay", "Perú", "Panamá", "Uruguay", "Costa Rica", "Guatemala",
          "Honduras", "REP DOM"]
AGREGADOS = {"GLOBAL": "Global", "LATINO": "Latinoamérica"}


def candidatas_desde_api() -> list[str]:
    """La página carga su contenido por una API; si el BCRD muda el archivo, el enlace
    nuevo aparece ahí. Se suma a las direcciones conocidas, no las reemplaza."""
    try:
        crudo = descargar(API, FUENTES / "embi" / "_api.json", intentos=2, referer=PAGINA,
                          post={"id": "2585", "languageName": "es"})
        texto = crudo.decode("utf-8", "ignore").replace("\\/", "/")
        return sorted(set(re.findall(r"https://[^\"'\s]+Spread[^\"'\s]*EMBI[^\"'\s]*\.xlsx", texto)))
    except Exception as e:  # noqa: BLE001
        print(f"   (la API del BCRD no respondió: {e}; sigo con las direcciones conocidas)")
        return []


def leer(ruta) -> dict:
    ws = openpyxl.load_workbook(ruta, read_only=True, data_only=True).worksheets[0]
    filas = list(ws.iter_rows(values_only=True))
    cab = next((i for i, f in enumerate(filas[:20]) if f and norm(f[0]) == "FECHA"), None)
    if cab is None:
        raise FuenteError("no encuentro la fila de encabezado «Fecha»")
    columnas = {j: str(c).strip() for j, c in enumerate(filas[cab]) if c and j > 0}
    if "Bolivia" not in columnas.values():
        raise FuenteError("la columna «Bolivia» ya no está en el Excel del EMBI")
    fechas, series = [], {n: [] for n in columnas.values()}
    for f in filas[cab + 1:]:
        d = f[0]
        if isinstance(d, str):
            try:
                d = dt.datetime.strptime(d.strip()[:10], "%Y-%m-%d")
            except ValueError:
                continue
        if not isinstance(d, dt.datetime):
            continue
        fechas.append(d.date())
        for j, n in columnas.items():
            v = num(f[j]) if j < len(f) else None
            series[n].append(None if v is None else round(v * 100))   # p.p. → pb
    return {"fechas": fechas, "series": series}


def validar(t: dict) -> None:
    f = t["fechas"]
    if any(b <= a for a, b in zip(f, f[1:])):
        raise FuenteError("las fechas del EMBI no son estrictamente crecientes")
    bol = [v for v in t["series"]["Bolivia"] if v is not None]
    if len(bol) < 1000:
        raise FuenteError(f"Bolivia trae sólo {len(bol)} observaciones")
    if min(bol) < 0 or max(bol) > 10000:
        raise FuenteError(f"spread de Bolivia fuera de rango: {min(bol)}–{max(bol)} pb")


def main() -> int:
    urls = list(dict.fromkeys(CANDIDATAS + candidatas_desde_api()))
    mejor = None
    for i, url in enumerate(urls):
        ruta = FUENTES / "embi" / f"embi_{i}.xlsx"
        try:
            crudo = descargar(url, ruta)
            t = leer(ruta)
        except Exception as e:  # noqa: BLE001
            print(f"   {url}: {e}")
            continue
        print(f"   {url.split('/')[2]}: último dato {t['fechas'][-1]}")
        if mejor is None or t["fechas"][-1] > mejor[1]["fechas"][-1]:
            mejor = (url, t, crudo)
    if mejor is None:
        raise FuenteError("ninguna dirección del EMBI respondió con un Excel legible")
    url, t, crudo = mejor
    validar(t)

    # Serie diaria desde la primera cotización de Bolivia (los bonos soberanos son de 2012).
    bol = t["series"]["Bolivia"]
    i0 = next(i for i, v in enumerate(bol) if v is not None)
    fechas = [d.isoformat() for d in t["fechas"][i0:]]
    diario = {"Bolivia": bol[i0:]}
    for clave, nombre in AGREGADOS.items():
        col = next((c for c in t["series"] if norm(c) == clave), None)
        if col is None:
            raise FuenteError(f"falta el agregado {clave} en el EMBI")
        diario[nombre] = t["series"][col][i0:]

    # Comparación regional: último dato de cada país y el de hace un año.
    ultimo = t["fechas"][-1]
    hace_un_anio = ultimo.replace(year=ultimo.year - 1)
    j_1a = max(i for i, d in enumerate(t["fechas"]) if d <= hace_un_anio)
    paises = []
    for p in REGION:
        col = next((c for c in t["series"] if norm(c) == norm(p)), None)
        if col is None:
            continue
        s = t["series"][col]
        k = max((i for i, v in enumerate(s) if v is not None), default=None)
        if k is None or t["fechas"][k] < ultimo - dt.timedelta(days=10):
            continue   # país que dejó de cotizar (p. ej. Venezuela): no entra en la foto de hoy
        paises.append({"pais": "Rep. Dominicana" if p == "REP DOM" else p,
                       "pb": s[k], "pb_hace_un_anio": s[j_1a]})
    paises.sort(key=lambda x: x["pb"], reverse=True)

    guardar_json("embi.json", {
        "meta": {
            "indicador": "Riesgo país: spread del EMBI Global Diversified",
            "unidad": "puntos básicos",
            "fuente": "J.P. Morgan, publicado por el Banco Central de la República Dominicana",
            "url": url, "pagina": PAGINA,
            "ultimo_dato": ultimo.isoformat(),
        },
        "fechas": fechas, "series": diario,
        "region": {"fecha": ultimo.isoformat(), "fecha_hace_un_anio": t["fechas"][j_1a].isoformat(),
                   "paises": paises},
    })
    registrar("embi", url=url, huella=huella(crudo), ultimo_dato=ultimo.isoformat(),
              observaciones_bolivia=sum(v is not None for v in bol))
    print(f"   Bolivia {ultimo}: {bol[-1]} pb · Latinoamérica {diario['Latinoamérica'][-1]} pb")
    # Diario: más de 5 días hábiles sin dato ya no es un feriado.
    verificar_frescura("EMBI", ultimo, max_dias_habiles=5)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FuenteError as e:
        print(f"ERROR EMBI: {e}")
        sys.exit(1)
