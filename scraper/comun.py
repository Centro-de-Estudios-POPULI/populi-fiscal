"""
Piezas comunes de los scrapers del Monitor Fiscal.

Tres reglas que valen para todas las fuentes (aprendidas en los otros monitores):

1. DESCARGAR ≠ PUBLICAR. Si una descarga falla, el JSON anterior queda intacto: vale
   más el último dato bueno que un monitor vacío. El fallo se informa (código de salida
   distinto de cero), no se esconde.
2. MAPEAR POR ETIQUETA, NUNCA POR FILA O COLUMNA FIJA. El BCB y el MEFP insertan filas,
   renombran rótulos y cambian formatos de un año a otro. Cada parser busca la etiqueta
   y aborta si no la encuentra.
3. LA SERIE TIENE QUE AVANZAR. Una fuente puede responder 200 con un archivo congelado
   (le pasó al TCO del BCB y al EMBI.xlsx viejo del Banco Central dominicano). Cada
   salida declara su último período y `verificar_frescura` falla si se queda atrás.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path

import requests
import urllib3

RAIZ = Path(__file__).resolve().parent.parent
FUENTES = RAIZ / "fuentes"          # descargas crudas (no se versionan)
DATA = RAIZ / "data"                # salidas limpias (sí se versionan)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# El MEFP sirve un certificado con la cadena incompleta: sin esto la descarga falla.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SIN_VERIFICAR = ("economiayfinanzas.gob.bo",)


class FuenteError(RuntimeError):
    """La fuente no se pudo leer o no dice lo que esperábamos. Nunca se tapa."""


def descargar(url: str, destino: Path, intentos: int = 4, referer: str | None = None,
              post: dict | None = None) -> bytes:
    """Baja un archivo con reintentos crecientes. El WAF del BCB corta conexiones de
    forma intermitente; esperar y reintentar suele alcanzar desde una máquina local."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    verificar = not any(d in url for d in SIN_VERIFICAR)
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    ultimo = None
    for i in range(intentos):
        try:
            if post is None:
                r = requests.get(url, headers=headers, timeout=120, verify=verificar)
            else:
                r = requests.post(url, headers=headers, data=post, timeout=120, verify=verificar)
            r.raise_for_status()
            if len(r.content) < 200:
                raise FuenteError(f"respuesta demasiado corta ({len(r.content)} bytes)")
            destino.write_bytes(r.content)
            return r.content
        except Exception as e:  # noqa: BLE001 — se reintenta cualquier fallo de red
            ultimo = e
            espera = 6 * (i + 1)
            print(f"   intento {i + 1}/{intentos} falló ({type(e).__name__}: {e}); espero {espera}s")
            time.sleep(espera)
    raise FuenteError(f"no se pudo descargar {url}: {ultimo}")


def huella(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()[:16]


def norm(txt) -> str:
    """Normaliza un rótulo para compararlo: sin tildes, mayúsculas, espacios simples,
    sin llamadas de nota (`2/`, `(p)`)."""
    if txt is None:
        return ""
    s = unicodedata.normalize("NFKD", str(txt))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\(p\)|\d+/", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip().upper()


def num(v):
    """Convierte una celda a número. Los Excel del MEFP guardan cifras como TEXTO."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--", "N/A", "n/a", "…", "..."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def guardar_json(nombre: str, obj: dict) -> Path:
    """Escribe una salida en data/ con separadores compactos y orden estable."""
    DATA.mkdir(parents=True, exist_ok=True)
    ruta = DATA / nombre
    ruta.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"   → data/{nombre} ({ruta.stat().st_size / 1024:.0f} KB)")
    return ruta


def registrar(clave: str, **datos) -> None:
    """Lleva el registro de procedencia de cada fuente: de dónde salió, cuándo se bajó,
    su huella y hasta qué período llega. Es lo que el monitor muestra como «fuente»."""
    ruta = DATA / "_registro.json"
    reg = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    reg[clave] = {**datos, "revisado": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    ruta.write_text(json.dumps(reg, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def dias_habiles_entre(desde: dt.date, hasta: dt.date) -> int:
    n, d = 0, desde
    while d < hasta:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def verificar_frescura(nombre: str, ultimo: dt.date, max_dias_habiles: int | None = None,
                       max_meses: int | None = None) -> None:
    """Falla si la serie no avanza. Se llama DESPUÉS de guardar: primero se publica el
    último dato bueno, después se pone en rojo."""
    hoy = dt.date.today()
    if max_dias_habiles is not None:
        atraso = dias_habiles_entre(ultimo, hoy)
        if atraso > max_dias_habiles:
            raise FuenteError(f"{nombre}: el último dato es del {ultimo} "
                              f"({atraso} días hábiles de atraso; tolerancia {max_dias_habiles})")
    if max_meses is not None:
        meses = (hoy.year - ultimo.year) * 12 + hoy.month - ultimo.month
        if meses > max_meses:
            raise FuenteError(f"{nombre}: el último dato es de {ultimo:%Y-%m} "
                              f"({meses} meses de atraso; tolerancia {max_meses})")
