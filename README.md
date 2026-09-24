# Monitor Fiscal — Centro de Estudios POPULI

Las cuentas del Estado boliviano desde 2017: resultado fiscal, ingresos y gastos, deuda
externa e interna, financiamiento del Banco Central y riesgo país. Los gráficos
(`embed/`) se incrustan en <https://populi.org.bo/monitor-fiscal/>.

## Cómo se actualiza

```
pip install -r scraper/requirements.txt
python scraper/actualizar.py            # todo
python scraper/actualizar.py --diario   # sólo riesgo país + derivados
```

La Action `actualizar.yml` corre el riesgo país los días hábiles y todo lo demás los
lunes y jueves, y commitea `data/` aunque algún scraper falle (el WAF del BCB rechaza
de vez en cuando a los runners de GitHub: esa fuente conserva su último dato bueno).

## Fuentes y salidas

| Script | Fuente | Salida | Frecuencia |
|---|---|---|---|
| `embi.py` | BCRD, serie histórica del spread EMBI | `embi.json` | diaria |
| `pib.py` | INE, PIB nominal trimestral, referencia 2017 | `pib.json` | trimestral |
| `spnf.py` | MEFP, operaciones consolidadas SPNF / GG / EP | `spnf.json` | mensual |
| `bcb_financiamiento.py` | BCB, financiamiento neto al sector público | `bcb_financiamiento.json` | mensual |
| `bcb_osf.py` | BCB, cuentas monetarias de otras sociedades financieras | `bcb_osf.json` | mensual |
| `deuda_externa.py` | BCB, deuda externa pública (8 cuadros) | `deuda_externa.json` | trimestral |
| `deuda_externa_tgn.py` | MEFP, deuda externa del TGN por acreedor | `deuda_externa_tgn.json` | mensual |
| `deuda_interna.py` | MEFP, deuda interna del TGN por tenedor | `deuda_interna.json` | mensual |
| `aps_cartera.py` | APS, cartera de los Fondos del SIP (PDF mensual) | `sip_cartera.json` | mensual |
| `conciliar.py` | cruce BCB ↔ MEFP | `conciliacion.json`, `salidas/conciliacion.txt` | — |
| `indicadores.py` | ratios, acumulados, encabezado | `indicadores.json` | — |

`data/_registro.json` guarda, por fuente, la URL, la huella del archivo y hasta qué
período llega.

## Decisiones metodológicas

- **Desde 2017**: el PIB nominal con año de referencia 2017 empieza ahí; mezclar bases
  cambiaría cualquier ratio sin que la política fiscal cambie.
- **Resultado primario** = resultado global + intereses (externos e internos).
- **Deuda en dólares → bolivianos**: Bs 6,86 por dólar (oficial de compra) hasta el
  26-jun-2026; desde entonces, el tipo de cambio oficial vigente (repositorio Dolar_Bolivia).
- **Deuda bruta del TGN** = externa (MEFP) + interna (MEFP), incluida la deuda con el BCB.
- El año en curso se compara en bolivianos hasta que el INE publique su PIB.

## Lo que las fuentes no permiten (declarado en el monitor)

- Deuda interna del TGN anterior a diciembre de 2022 (el MEFP no la publica en su página).
- Cuánto de la deuda del TGN tienen los fondos de pensiones: el MEFP la registra dentro
  de «Mercado financiero (subasta)». Se aproxima con la cartera del SIP que publica la APS
  (valor de mercado: la columna nominal cambió de definición con el traspaso a la Gestora).
  Seis meses de la APS no se pueden leer (PDF escaneado o con el gráfico sobre la tabla):
  quedan como huecos declarados.
- La brecha estable (≈ Bs 6.100–7.900 millones) entre el crédito bruto del BCB al Gobierno
  Central y la deuda del TGN con el BCB que informa el MEFP.
