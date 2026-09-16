// An interface for ahkab -- a small SVG line chart with a hover readout.
//
// Copyright 2026 Roberto Perez-Franco
// SPDX-License-Identifier: GPL-2.0-or-later
//
// One chart has one y-axis. Quantities with different units go on separate
// charts; the caller decides which series share one.

const SVG = 'http://www.w3.org/2000/svg';
const PREFIXES = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'],
                  [1e-6, 'µ'], [1e-9, 'n'], [1e-12, 'p'], [1e-15, 'f']];

/** Engineering notation: 0.0015 -> "1.5 m", with the unit appended. */
export function eng(value, unit = '', digits = 4) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  if (value === 0) return '0' + (unit ? ' ' + unit : '');
  // Logarithmic and angular units take no SI prefix: "-3 dB", not "-3000 mdB".
  if (/^dB/.test(unit) || unit === '°') {
    return String(Number(value.toPrecision(digits))) + (unit === '°' ? unit : ' ' + unit);
  }
  const abs = Math.abs(value);
  let [scale, prefix] = PREFIXES[PREFIXES.length - 1];
  for (const [s, p] of PREFIXES) { if (abs >= s * 0.9999999) { scale = s; prefix = p; break; } }
  if (abs >= 1e12 || abs < 1e-18) return value.toExponential(digits - 1) + (unit ? ' ' + unit : '');
  const n = Number((value / scale).toPrecision(digits));
  const sep = unit || prefix ? ' ' : '';
  return String(n) + sep + prefix + unit;
}

function el(name, attrs, parent) {
  const node = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function niceStep(range, count) {
  const raw = range / Math.max(count, 1);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  return (norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10) * mag;
}

function linearTicks(lo, hi, count) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const step = niceStep(hi - lo, count);
  const start = Math.ceil(lo / step - 1e-9) * step;
  const ticks = [];
  for (let v = start; v <= hi + step * 1e-9; v += step) ticks.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return ticks;
}

function logTicks(lo, hi) {
  const ticks = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
    const v = Math.pow(10, e);
    if (v >= lo * 0.999999 && v <= hi * 1.000001) ticks.push(v);
  }
  return ticks;
}

/**
 * Draw a line chart into `container` (replacing its content).
 *
 * spec = {
 *   x: {values, log, name, unit},
 *   series: [{name, values, color}],      // values aligned with x.values
 *   yLabel, yUnit,
 *   ariaLabel,
 * }
 */
export function lineChart(container, spec) {
  container.textContent = '';
  container.classList.add('chart');
  const xs = spec.x.values;
  const series = spec.series;

  if (series.length > 1) {
    const legend = document.createElement('ul');
    legend.className = 'legend';
    for (const s of series) {
      const li = document.createElement('li');
      const key = document.createElement('span');
      key.className = 'legend-key';
      key.style.background = s.color;
      li.append(key, document.createTextNode(s.name));
      legend.appendChild(li);
    }
    container.appendChild(legend);
  }

  const frame = document.createElement('div');
  frame.className = 'chart-frame';
  container.appendChild(frame);
  const tip = document.createElement('div');
  tip.className = 'chart-tip';
  tip.hidden = true;
  frame.appendChild(tip);

  const draw = () => {
    for (const old of frame.querySelectorAll('svg')) old.remove();
    const width = Math.max(frame.clientWidth, 280);
    const height = Math.round(Math.min(320, Math.max(200, width * 0.5)));
    const m = { l: 76, r: 22, t: 10, b: 38 };
    const w = width - m.l - m.r, h = height - m.t - m.b;

    const logX = !!spec.x.log;
    const finite = (v) => v !== null && v !== undefined && Number.isFinite(v);
    const xVals = xs.filter((v) => finite(v) && (!logX || v > 0));
    let x0 = Math.min(...xVals), x1 = Math.max(...xVals);
    if (x0 === x1) { x1 = x0 + 1; }
    // A sweep that starts a hair above zero (a transient's first step, say)
    // should still show its axis from zero.
    if (!logX && x0 > 0 && x0 < (x1 - x0) * 0.02) x0 = 0;
    if (!logX && x1 < 0 && -x1 < (x1 - x0) * 0.02) x1 = 0;
    const ys = [];
    for (const s of series) for (const v of s.values) if (finite(v)) ys.push(v);
    let y0 = ys.length ? Math.min(...ys) : 0, y1 = ys.length ? Math.max(...ys) : 1;
    if (y0 === y1) { const d = Math.abs(y0) * 0.1 || 1; y0 -= d; y1 += d; }
    const pad = (y1 - y0) * 0.06;
    const yTicks = linearTicks(y0 - pad, y1 + pad, Math.max(3, Math.floor(h / 48)));
    y0 = Math.min(y0 - pad, yTicks[0]); y1 = Math.max(y1 + pad, yTicks[yTicks.length - 1]);

    const sx = logX
      ? (v) => m.l + (Math.log10(v) - Math.log10(x0)) / (Math.log10(x1) - Math.log10(x0)) * w
      : (v) => m.l + (v - x0) / (x1 - x0) * w;
    const sy = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * h;

    const svg = el('svg', { width, height, viewBox: `0 0 ${width} ${height}`, role: 'img',
      'aria-label': spec.ariaLabel || spec.yLabel || 'chart' });
    frame.insertBefore(svg, tip);

    const grid = el('g', { class: 'grid' }, svg);
    for (const v of yTicks) {
      const y = sy(v);
      el('line', { x1: m.l, x2: m.l + w, y1: y, y2: y }, grid);
      const label = el('text', { x: m.l - 8, y: y + 4, 'text-anchor': 'end', class: 'tick' }, svg);
      label.textContent = eng(v, spec.yUnit || '', 3);
    }
    const xTicks = logX ? logTicks(x0, x1) : linearTicks(x0, x1, Math.max(3, Math.floor(w / 90)));
    for (const v of xTicks) {
      const x = sx(v);
      el('line', { x1: x, x2: x, y1: m.t, y2: m.t + h }, grid);
      const label = el('text', { x, y: m.t + h + 18, 'text-anchor': 'middle', class: 'tick' }, svg);
      label.textContent = eng(v, spec.x.unit || '', 3);
    }
    el('line', { x1: m.l, x2: m.l + w, y1: m.t + h, y2: m.t + h, class: 'axis' }, svg);

    const xTitle = el('text', { x: m.l + w, y: height - 4, 'text-anchor': 'end', class: 'axis-title' }, svg);
    xTitle.textContent = spec.x.name;
    const yTitle = el('text', { x: 12, y: m.t + h / 2, 'text-anchor': 'middle', class: 'axis-title',
      transform: `rotate(-90 12 ${m.t + h / 2})` }, svg);
    yTitle.textContent = spec.yLabel;

    const plot = el('g', {}, svg);
    for (const s of series) {
      let d = '', pen = false;
      for (let i = 0; i < xs.length; i++) {
        const xv = xs[i], yv = s.values[i];
        if (!finite(xv) || !finite(yv) || (logX && xv <= 0)) { pen = false; continue; }
        d += (pen ? 'L' : 'M') + sx(xv).toFixed(1) + ' ' + sy(yv).toFixed(1);
        pen = true;
      }
      el('path', { d, class: 'line', style: `stroke: ${s.color}` }, plot);
    }

    // Hover readout: a crosshair at the nearest sample, one ringed marker per
    // series, and a tooltip listing every series at that x.
    const cross = el('line', { y1: m.t, y2: m.t + h, class: 'crosshair', visibility: 'hidden' }, svg);
    const dots = series.map((s) => el('circle', { r: 4, style: `fill: ${s.color}`, class: 'dot', visibility: 'hidden' }, svg));
    const hit = el('rect', { x: m.l, y: m.t, width: w, height: h, class: 'hit', tabindex: 0 }, svg);
    let current = -1;

    const nearest = (px) => {
      let best = -1, dist = Infinity;
      for (let i = 0; i < xs.length; i++) {
        if (!finite(xs[i]) || (logX && xs[i] <= 0)) continue;
        const dd = Math.abs(sx(xs[i]) - px);
        if (dd < dist) { dist = dd; best = i; }
      }
      return best;
    };
    const show = (i) => {
      if (i < 0) return;
      current = i;
      const x = sx(xs[i]);
      cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
      series.forEach((s, k) => {
        const v = s.values[i];
        if (finite(v)) {
          dots[k].setAttribute('cx', x); dots[k].setAttribute('cy', sy(v)); dots[k].setAttribute('visibility', 'visible');
        } else dots[k].setAttribute('visibility', 'hidden');
      });
      tip.textContent = '';
      const head = document.createElement('div');
      head.className = 'tip-head';
      head.textContent = spec.x.name + ' = ' + eng(xs[i], spec.x.unit);
      tip.appendChild(head);
      for (const s of series) {
        const row = document.createElement('div');
        row.className = 'tip-row';
        const key = document.createElement('span');
        key.className = 'legend-key';
        key.style.background = s.color;
        const name = document.createElement('span');
        name.textContent = s.name;
        const val = document.createElement('span');
        val.className = 'tip-val';
        val.textContent = eng(s.values[i], spec.yUnit);
        row.append(key, name, val);
        tip.appendChild(row);
      }
      tip.hidden = false;
      const tw = tip.offsetWidth;
      tip.style.left = Math.min(Math.max(x + 12, 0), width - tw - 4) + 'px';
      tip.style.top = (m.t + 4) + 'px';
      if (x + 12 + tw > width) tip.style.left = Math.max(x - tw - 12, 0) + 'px';
    };
    const hide = () => {
      current = -1;
      cross.setAttribute('visibility', 'hidden');
      dots.forEach((d) => d.setAttribute('visibility', 'hidden'));
      tip.hidden = true;
    };
    hit.addEventListener('pointermove', (e) => {
      const r = svg.getBoundingClientRect();
      show(nearest(e.clientX - r.left));
    });
    hit.addEventListener('pointerleave', hide);
    hit.addEventListener('blur', hide);
    hit.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      let i = current < 0 ? 0 : current + (e.key === 'ArrowRight' ? 1 : -1);
      i = Math.max(0, Math.min(xs.length - 1, i));
      show(i);
    });
  };

  draw();
  let lastWidth = frame.clientWidth;
  const ro = new ResizeObserver(() => {
    if (Math.abs(frame.clientWidth - lastWidth) > 4) { lastWidth = frame.clientWidth; draw(); }
  });
  ro.observe(frame);
}
