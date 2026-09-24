/* ════════════════════════════════════════════════════════════════════════════
   Monitor Fiscal POPULI — utilidades comunes de los gráficos incrustados.

   - Tema: la página del monitor manda {theme:'dark'|'light'} por postMessage (mismo
     protocolo que los otros monitores). `?tema=dark` sirve para probar suelto.
   - Números: formato boliviano (1.234,5), siempre con Intl 'es-BO'.
   - Ningún número se escribe acá: todo sale de ../data/*.json, que arman los scrapers.
   ════════════════════════════════════════════════════════════════════════════ */
(function () {
  const PF = {};
  const oyentes = [];

  // ── Tema ──────────────────────────────────────────────────────────────────
  PF.tema = function () { return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; };
  function ponerTema(t) {
    if (t !== 'dark' && t !== 'light') return;
    if (t === PF.tema() && document.documentElement.hasAttribute('data-theme')) return;
    document.documentElement.setAttribute('data-theme', t);
    oyentes.forEach(function (f) { f(); });
  }
  const q = new URLSearchParams(location.search).get('tema');
  document.documentElement.setAttribute('data-theme', q === 'dark' ? 'dark' : 'light');
  window.addEventListener('message', function (e) { if (e.data && e.data.theme) ponerTema(e.data.theme); });
  // Saludo: el gráfico puede cargar ANTES de que la página empiece a escuchar (y perderse
  // el aviso del tema). Por eso avisa que está listo y la página le contesta con el tema.
  if (window.parent !== window) window.parent.postMessage({ populiListo: true }, '*');
  PF.alCambiarTema = function (f) { oyentes.push(f); };

  // Colores leídos de las variables CSS del tema vigente (una sola fuente: comun.css).
  PF.c = function () {
    const s = getComputedStyle(document.documentElement);
    const v = function (n) { return s.getPropertyValue('--' + n).trim(); };
    return { bg: v('bg'), card: v('card'), ink: v('ink'), muted: v('muted'), grid: v('grid'), line: v('line'),
             accent: v('accent'), neg: v('neg'), pos: v('pos'), c3: v('c3'), g1: v('g1'), g2: v('g2'), g3: v('g3') };
  };

  // ── Números y fechas ─────────────────────────────────────────────────────
  const nf = {};
  PF.num = function (x, dec) {
    if (x === null || x === undefined || isNaN(x)) return '—';
    dec = dec === undefined ? 1 : dec;
    const k = String(dec);
    nf[k] = nf[k] || new Intl.NumberFormat('es-BO', { minimumFractionDigits: dec, maximumFractionDigits: dec });
    return nf[k].format(x).replace('-', '−');   // signo menos tipográfico, no guion
  };
  PF.signo = function (x, dec) { return (x > 0 ? '+' : '') + PF.num(x, dec); };
  PF.MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  PF.MESES_L = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  PF.mes = function (ym) { return PF.MESES[parseInt(ym.slice(5, 7), 10) - 1] + ' ' + ym.slice(0, 4); };
  PF.mesLargo = function (ym) { return PF.MESES_L[parseInt(ym.slice(5, 7), 10) - 1] + ' de ' + ym.slice(0, 4); };
  PF.dia = function (iso) {
    const d = new Date(iso + 'T00:00:00');
    return d.getDate() + ' ' + PF.MESES[d.getMonth()] + ' ' + d.getFullYear();
  };
  PF.trim = function (p) { return p.replace(/^(\d{4})-T(\d)$/, '$2T $1'); };   // "2026-T2" → "2T 2026"

  // ── Datos ─────────────────────────────────────────────────────────────────
  PF.cargar = function (nombres) {
    const v = new Date().toISOString().slice(0, 10);   // una vez por día, sin caché vieja
    return Promise.all(nombres.map(function (n) {
      return fetch('../data/' + n + '?v=' + v).then(function (r) {
        if (!r.ok) throw new Error(n + ': ' + r.status);
        return r.json();
      });
    }));
  };
  PF.error = function (el, e) {
    el.innerHTML = '<div class="error">No se pudieron cargar los datos (' + (e && e.message ? e.message : e) +
      '). El gráfico no muestra cifras de reserva: vuelva a intentar más tarde.</div>';
    console.error(e);
  };

  // ── ECharts: piezas comunes ───────────────────────────────────────────────
  PF.pequeño = function () { return window.innerWidth <= 560; };
  PF.tooltip = function (extra) {
    const c = PF.c();
    return Object.assign({
      trigger: 'axis', confine: true, className: 'tt',
      backgroundColor: c.card, borderColor: c.line, borderWidth: 1, padding: [8, 10],
      textStyle: { color: c.ink, fontFamily: 'Inter', fontSize: 12 },
      extraCssText: 'border-radius:0;box-shadow:0 4px 14px rgba(0,0,0,.12);',
      axisPointer: { type: 'line', lineStyle: { color: c.muted, width: 1, type: 'dashed' } }
    }, extra || {});
  };
  PF.ejeX = function (datos, extra) {
    const c = PF.c();
    return Object.assign({
      type: 'category', data: datos, boundaryGap: true,
      axisLine: { lineStyle: { color: c.line } }, axisTick: { show: false },
      axisLabel: { color: c.muted, fontFamily: 'Inter', fontSize: 11, hideOverlap: true }
    }, extra || {});
  };
  PF.ejeY = function (fmt, extra) {
    const c = PF.c();
    return Object.assign({
      type: 'value', splitNumber: PF.pequeño() ? 4 : 5,
      axisLabel: { color: c.muted, fontFamily: 'JetBrains Mono', fontSize: 10.5, formatter: fmt },
      splitLine: { lineStyle: { color: c.grid } }, axisLine: { show: false }, axisTick: { show: false }
    }, extra || {});
  };
  PF.grid = function (extra) {
    return Object.assign({ left: 8, right: 14, top: 18, bottom: 8, containLabel: true }, extra || {});
  };
  // Línea tooltip: marcador cuadrado + nombre + valor.
  PF.fila = function (color, nombre, valor, forma) {
    const m = forma === 'linea'
      ? '<span style="display:inline-block;width:12px;height:0;border-top:2px solid ' + color + ';margin-right:6px;vertical-align:middle"></span>'
      : '<span style="display:inline-block;width:9px;height:9px;background:' + color + ';margin-right:6px"></span>';
    return '<div style="display:flex;justify-content:space-between;gap:14px;line-height:1.7">' +
      '<span>' + m + nombre + '</span><b style="font-family:JetBrains Mono,monospace">' + valor + '</b></div>';
  };

  // Monta un gráfico que se redibuja solo al cambiar el tema o el ancho.
  PF.montar = function (el, dibujar) {
    let chart = echarts.init(el, null, { renderer: 'canvas' });
    const pintar = function () { chart.setOption(dibujar(), true); };
    PF.alCambiarTema(function () { chart.dispose(); chart = echarts.init(el, null, { renderer: 'canvas' }); pintar(); });
    let ancho = window.innerWidth;
    new ResizeObserver(function () { chart.resize(); }).observe(el);
    window.addEventListener('resize', function () {
      const pasó = (ancho <= 560) !== (window.innerWidth <= 560);
      ancho = window.innerWidth;
      if (pasó) pintar();
    });
    pintar();
    return { redibujar: pintar, get chart() { return chart; } };
  };

  // Botonera segmentada. opciones: [[valor, rótulo], ...]
  PF.segmento = function (el, opciones, activo, alCambiar) {
    el.innerHTML = '';
    opciones.forEach(function (o) {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = o[1]; b.setAttribute('aria-pressed', String(o[0] === activo));
      b.addEventListener('click', function () {
        el.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
        b.setAttribute('aria-pressed', 'true');
        alCambiar(o[0]);
      });
      el.appendChild(b);
    });
  };

  PF.leyenda = function (el, items) {
    el.innerHTML = items.map(function (it) {
      const cls = it.forma === 'linea' ? 'linea' : it.forma === 'punto' ? 'punto' : '';
      const est = it.forma === 'linea' || it.forma === 'punto' ? 'border-color:' + it.color : 'background:' + it.color;
      return '<span><i class="' + cls + '" style="' + est + '"></i>' + it.nombre + '</span>';
    }).join('');
  };

  // ── Altura: incrustado en la página del monitor, avisa cuánto mide para que el
  // iframe se ajuste (sin alto fijo que corte en el teléfono o sobre en la PC).
  if (window.parent !== window) {
    let ultimo = 0;
    const avisar = function () {
      const h = Math.ceil(document.documentElement.getBoundingClientRect().height);
      if (Math.abs(h - ultimo) > 2) { ultimo = h; window.parent.postMessage({ populiAltura: h }, '*'); }
    };
    window.addEventListener('load', avisar);
    new ResizeObserver(avisar).observe(document.documentElement);
    document.addEventListener('toggle', avisar, true);   // abrir/cerrar «Cómo se calcula»
  }

  window.PF = PF;
})();
