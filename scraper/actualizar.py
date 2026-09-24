"""
Orquestador del Monitor Fiscal: corre los scrapers y después los derivados.

    python scraper/actualizar.py            # todo (lo que corre el lunes)
    python scraper/actualizar.py --diario   # sólo el riesgo país + derivados

Cada scraper corre en su propio proceso: si uno falla (p. ej. el WAF del BCB le da un
403 a la IP del runner), los demás igual actualizan y su JSON anterior queda intacto.
Al final se sale con error si algo falló, para que la notificación llegue.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
FUENTES = ["embi.py", "pib.py", "spnf.py", "bcb_financiamiento.py", "bcb_osf.py",
           "deuda_externa.py", "deuda_externa_tgn.py", "deuda_interna.py"]
DIARIO = ["embi.py"]
DERIVADOS = ["conciliar.py", "indicadores.py"]


def correr(script: str) -> bool:
    print(f"\n═══ {script} ═══", flush=True)
    r = subprocess.run([sys.executable, str(AQUI / script)], cwd=AQUI)
    if r.returncode != 0:
        print(f"::warning::falló {script}", flush=True)
    return r.returncode == 0


def main() -> int:
    lista = DIARIO if "--diario" in sys.argv else FUENTES
    fallos = [s for s in lista if not correr(s)]
    # Los derivados se recalculan siempre con lo que haya en data/: si una fuente falló,
    # usan su último dato bueno (y su propia fecha de corte lo dice).
    fallos += [s for s in DERIVADOS if not correr(s)]
    print("\n═══ resumen ═══")
    if fallos:
        print("con error:", ", ".join(fallos))
        return 1
    print("todo actualizado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
