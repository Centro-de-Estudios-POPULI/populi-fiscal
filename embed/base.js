/* ════════════════════════════════════════════════════════════════════════════
   Monitor Fiscal POPULI — piezas comunes, con el MISMO lenguaje que el Monitor
   Monetario (determinantes_base.html): tooltip oscuro con la fecha en rojo claro,
   ejes, pastillas de serie rellenas con su color, ítems del panel de lectura y
   preguntas desplegables. Ningún número se escribe acá: todo sale de ../data/*.json.
   ════════════════════════════════════════════════════════════════════════════ */
(function () {
  const PF = {};

  // ── Paleta: la de la marca (populi-marca/paleta.json), por familias ────────
  PF.C = {
    rojo: '#C71E1D', rojoClaro: '#E8706B', rojoOscuro: '#8B1A1A',
    turquesa: '#0A9396', menta: '#94D2BD', petroleo: '#005F73',
    oro: '#EE9B00', arena: '#E9D8A6', oroOscuro: '#A86E00',
    naranja: '#E57D22', tierra: '#DF5D25', granate: '#9B2226',
    gris: '#94A3B8', grisOscuro: '#64748B'
  };
  PF.dk = function () { return document.documentElement.getAttribute('data-theme') === 'dark'; };
  PF.tinta = function () { return PF.dk() ? '#F1F5F9' : '#0D1B2A'; };

  // ── Tema (mismo protocolo que los otros monitores) + saludo y altura ───────
  const oyentes = [];
  PF.alCambiarTema = function (f) { oyentes.push(f); };
  const q = new URLSearchParams(location.search).get('tema');
  document.documentElement.setAttribute('data-theme', q === 'dark' ? 'dark' : 'light');
  window.addEventListener('message', function (e) {
    if (e.data && e.data.theme && e.data.theme !== document.documentElement.getAttribute('data-theme')) {
      document.documentElement.setAttribute('data-theme', e.data.theme);
      oyentes.forEach(function (f) { f(); });
    }
  });
  if (window.parent !== window) {
    // El gráfico puede cargar antes de que la página escuche: saluda y la página le
    // contesta con el tema. Y avisa cuánto mide, para que el iframe no corte ni sobre.
    window.parent.postMessage({ populiListo: true }, '*');
    let ultimo = 0;
    const avisar = function () {
      const h = Math.ceil(document.documentElement.getBoundingClientRect().height);
      if (Math.abs(h - ultimo) > 2) { ultimo = h; window.parent.postMessage({ populiAltura: h }, '*'); }
    };
    window.addEventListener('load', avisar);
    new ResizeObserver(avisar).observe(document.documentElement);
    document.addEventListener('click', function () { setTimeout(avisar, 60); });
  }

  // ── Números y fechas (formato boliviano, signo menos tipográfico) ──────────
  const cache = {};
  PF.num = function (x, dec) {
    if (x === null || x === undefined || isNaN(x)) return '—';
    dec = dec === undefined ? 1 : dec;
    cache[dec] = cache[dec] || new Intl.NumberFormat('es-BO', { minimumFractionDigits: dec, maximumFractionDigits: dec });
    return cache[dec].format(x).replace('-', '−');
  };
  PF.signo = function (x, dec) { return (x > 0 ? '+' : '') + PF.num(x, dec); };
  PF.corto = function (v) {       // 152.071 → «152k» (ejes)
    const a = Math.abs(v), s = v < 0 ? '−' : '';
    return a >= 1000 ? s + PF.num(a / 1000, 0) + 'k' : s + PF.num(a, 0);
  };
  PF.MES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
  PF.MES_L = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
  PF.mes = function (ym) { return PF.MES[+ym.slice(5, 7) - 1] + ' ' + ym.slice(0, 4); };
  PF.mesLargo = function (ym) { return PF.MES_L[+ym.slice(5, 7) - 1] + ' de ' + ym.slice(0, 4); };
  PF.trim = function (p) { return p.replace(/^(\d{4})-T(\d)$/, '$2T $1'); };
  PF.dia = function (iso) { const d = new Date(iso + 'T00:00:00'); return d.getDate() + ' ' + PF.MES[d.getMonth()].toLowerCase() + ' ' + d.getFullYear(); };

  PF.cargar = function (nombres) {
    const v = new Date().toISOString().slice(0, 10);
    return Promise.all(nombres.map(function (n) {
      return fetch('../data/' + n + '?v=' + v).then(function (r) { if (!r.ok) throw new Error(n + ': ' + r.status); return r.json(); });
    }));
  };

  // ── ECharts con el estilo del Monetario ─────────────────────────────────────
  PF.ejeX = function (etiquetas, extra) {
    const d = PF.dk();
    return Object.assign({
      type: 'category', data: etiquetas, boundaryGap: true,
      axisLine: { lineStyle: { color: d ? '#2A3A50' : '#E2E8F0' } }, axisTick: { show: false },
      axisLabel: { fontFamily: 'Inter', fontSize: 10, fontWeight: 500, color: d ? '#555' : '#64748B' }
    }, extra || {});
  };
  PF.ejeY = function (formato, extra) {
    const d = PF.dk();
    return Object.assign({
      type: 'value', axisLine: { show: false },
      splitLine: { lineStyle: { color: d ? 'rgba(42,58,80,.5)' : '#F1F5F9' } },
      axisLabel: { fontFamily: 'JetBrains Mono', fontSize: 11, color: d ? '#555' : '#64748B', formatter: formato }
    }, extra || {});
  };
  // Eje de tiempo mensual («2026-07») o trimestral («2026-T2»): un rótulo por año, derecho,
  // en el primer período del año; cada 2 o 4 años si la serie es larga o la pantalla chica.
  PF.ejeTiempo = function (claves, extra) {
    const d = PF.dk(), anios = new Set(claves.map(function (k) { return k.slice(0, 4); })).size;
    const paso = anios > 12 ? (PF.pequeno() ? 4 : 2) : (PF.pequeno() && anios > 6 ? 2 : 1);
    return PF.ejeX(claves, Object.assign({
      boundaryGap: false,
      axisLabel: { fontFamily: 'Inter', fontSize: 10, fontWeight: 500, color: d ? '#555' : '#64748B',
        interval: function (i) { return /-(01|T1)$/.test(claves[i]) && (+claves[i].slice(0, 4)) % paso === 0; },
        formatter: function (v) { return v.slice(0, 4); } }
    }, extra || {}));
  };
  PF.tooltip = function (formatter, extra) {
    const d = PF.dk();
    return Object.assign({
      trigger: 'axis', confine: true,
      axisPointer: { type: 'shadow', shadowStyle: { color: d ? 'rgba(255,255,255,.04)' : 'rgba(13,27,42,.05)' } },
      backgroundColor: 'rgba(0,18,25,.96)', borderColor: d ? '#2A3A50' : '#1A2940', borderWidth: 1, padding: 14,
      extraCssText: 'border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,.3);',
      textStyle: { fontFamily: 'Inter', fontSize: 12, color: '#fff' },
      formatter: formatter
    }, extra || {});
  };
  PF.ttTitulo = function (t) { return '<div style="font-weight:700;margin-bottom:6px;color:#E8706B">' + t + '</div>'; };
  PF.ttFila = function (color, nombre, valor) {
    return '<div style="display:flex;align-items:center;gap:6px;margin-top:4px">' +
      '<span style="width:8px;height:8px;border-radius:50%;background:' + color + ';display:inline-block"></span>' +
      '<span style="font-size:11px">' + nombre + ':</span>' +
      '<span style="font-family:JetBrains Mono;font-weight:700;color:' + color + '">' + valor + '</span></div>';
  };
  PF.ttPie = function (html) {
    return '<div style="margin-top:6px;padding-top:5px;border-top:1px solid rgba(255,255,255,.15);font-size:10.5px;color:#E2DDD3">' + html + '</div>';
  };

  // ── Botoneras (medida / rango) y pastillas de serie ─────────────────────────
  PF.botonera = function (el, opciones, activo, alCambiar) {
    el.innerHTML = opciones.map(function (o) {
      return '<button class="hz-btn' + (o[0] === activo ? ' active' : '') + '" data-v="' + o[0] + '">' + o[1] + '</button>';
    }).join('');
    el.querySelectorAll('button').forEach(function (b) {
      b.addEventListener('click', function () {
        el.querySelectorAll('button').forEach(function (x) { x.classList.toggle('active', x === b); });
        alCambiar(b.dataset.v);
      });
    });
  };
  PF.pastillas = function (el, series, activas, alCambiar) {
    el.innerHTML = '';
    series.forEach(function (s) {
      const b = document.createElement('button');
      b.className = 'pill'; b.dataset.k = s.k;
      b.innerHTML = '<span class="lp' + (s.punteada ? ' dashed' : '') + '"></span>' + s.nombre;
      b.addEventListener('click', function () {
        if (activas.has(s.k)) { if (activas.size > 1) activas.delete(s.k); } else activas.add(s.k);
        pintar(); alCambiar();
      });
      el.appendChild(b);
    });
    function pintar() {
      el.querySelectorAll('.pill').forEach(function (b) {
        const s = series.find(function (x) { return x.k === b.dataset.k; });
        const c = typeof s.color === 'function' ? s.color() : s.color, on = activas.has(s.k);
        b.style.backgroundColor = on ? c : 'transparent'; b.style.color = on ? (PF.dk() && c === '#F1F5F9' ? '#0D1B2A' : '#fff') : c;
        b.style.borderColor = c;
        b.querySelector('.lp').style.borderColor = on ? (PF.dk() && c === '#F1F5F9' ? '#0D1B2A' : '#fff') : c;
      });
    }
    pintar();
    PF.alCambiarTema(pintar);
  };

  // ── Panel de lectura y preguntas ─────────────────────────────────────────────
  function rgba(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
  }
  PF.pb = function (color, rotulo, valor, desc) {
    return '<div class="pb"><div class="pb-lbl" style="color:' + color + ';background:' + rgba(color.length === 7 ? color : '#0D1B2A', 0.08) +
      ';border-left-color:' + color + '">' + rotulo + '</div>' +
      '<div class="pb-val" style="color:' + color + '">' + valor + '</div>' +
      (desc ? '<p class="pb-desc">' + desc + '</p>' : '') + '</div>';
  };
  PF.ctx = function (html) { return '<div class="ctx"><p>' + html + '</p></div>'; };
  PF.kpi = function (color, rotulo, valor, delta, tono) {
    return '<div class="kpi" style="cursor:default"><div style="position:absolute;top:0;left:0;width:100%;height:3px;background:' + color + '"></div>' +
      '<div class="kpi-lbl">' + rotulo + '</div><div class="kpi-val" style="color:' + color + '">' + valor + '</div>' +
      '<div class="kpi-d ' + (tono || 'flat') + '">' + delta + '</div></div>';
  };
  PF.preguntas = function (el, lista) {
    el.innerHTML = lista.map(function (p) {
      return '<div class="edu"><div class="edu-t">' + p[0] +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg></div>' +
        '<div class="edu-body">' + p[1] + '</div></div>';
    }).join('');
    el.querySelectorAll('.edu').forEach(function (e) { e.addEventListener('click', function () { e.classList.toggle('open'); }); });
  };

  // Monta un gráfico que se redibuja con el tema y el ancho.
  PF.montar = function (el, opciones) {
    let chart = echarts.init(el);
    const pintar = function () { chart.setOption(opciones(), true); };
    PF.alCambiarTema(function () { chart.dispose(); chart = echarts.init(el); pintar(); });
    window.addEventListener('resize', function () { chart.resize(); });
    pintar();
    return { redibujar: pintar, get chart() { return chart; } };
  };
  PF.pequeno = function () { return window.innerWidth <= 560; };

  window.PF = PF;
})();
