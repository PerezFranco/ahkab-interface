// An interface for ahkab -- the page.
//
// Copyright 2026 Roberto Perez-Franco
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Simulation engine: ahkab, by Giuseppe Venturini. This file only handles the
// editor, talks to worker.js, and displays what comes back.

import { lineChart, eng } from './chart.js';

// Reference categorical palette, validated for light and dark surfaces.
// A series keeps its slot while it is shown; slots are never cycled.
const PALETTE_SIZE = 8;

const $ = (sel) => document.querySelector(sel);
const editor = $('#netlist');
const runButton = $('#run');
const exampleSelect = $('#example');
const statusText = $('#status-text');
const statusDot = $('#status');
const deferredText = $('#deferred-text');
const deferredChip = $('#deferred');
const results = $('#results');

const state = { ready: false, deferred: 'waiting', nextId: 1, running: null, timings: null };
window.__ifc = state;  // read by the local tests

const STAGES = {
  runtime: 'Loading Python…',
  packages: 'Loading numerical libraries…',
  engine: 'Loading ahkab…',
};

const worker = new Worker('worker.js', { type: 'module' });
worker.onmessage = (event) => {
  const msg = event.data;
  if (msg.type === 'status') {
    setStatus('loading', STAGES[msg.stage] || 'Loading…');
  } else if (msg.type === 'ready') {
    state.ready = true;
    state.timings = msg.timings;
    setStatus('ready', 'Ready');
    statusDot.title = `Ready in ${(msg.timings.total / 1000).toFixed(1)} s`;
    runButton.disabled = false;
  } else if (msg.type === 'deferred') {
    state.deferred = msg.state;
    if (msg.state === 'loading') {
      deferredChip.dataset.state = 'loading';
      deferredText.textContent = 'Symbolic and FFT tools loading…';
    } else {
      state.deferredSeconds = msg.seconds;
      deferredChip.dataset.state = 'ready';
      deferredText.textContent = 'All tools ready';
    }
  } else if (msg.type === 'result') {
    if (!state.running || state.running.id !== msg.id) return;
    const elapsedPage = performance.now() - state.running.started;
    state.running = null;
    runButton.disabled = false;
    runButton.textContent = 'Run';
    state.lastResult = msg.result;
    render(msg.result, elapsedPage);
  } else if (msg.type === 'fatal') {
    setStatus('error', 'Could not start: ' + msg.message);
    state.fatal = msg;
  }
};

function setStatus(kind, text) {
  statusDot.dataset.state = kind;
  statusText.textContent = text;
}

function run() {
  if (!state.ready || state.running) return;
  const id = state.nextId++;
  state.running = { id, started: performance.now() };
  runButton.disabled = true;
  runButton.textContent = state.deferred === 'loading' && /^\s*\.(symbolic|fft)\b/im.test(editor.value)
    ? 'Waiting for tools…' : 'Running…';
  worker.postMessage({ type: 'run', id, netlist: editor.value });
}

runButton.addEventListener('click', run);
editor.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
});

// ---------- examples ----------

async function loadExamples() {
  const response = await fetch('examples/examples.json');
  const data = await response.json();
  for (const ex of data.examples) {
    const option = document.createElement('option');
    option.value = ex.file;
    option.textContent = `${ex.title} — ${ex.analyses}`;
    exampleSelect.appendChild(option);
  }
  exampleSelect.addEventListener('change', () => loadExample(exampleSelect.value));
  await loadExample(data.examples[0].file);
}

async function loadExample(file) {
  const response = await fetch('examples/' + file);
  editor.value = await response.text();
  exampleSelect.value = file;
}

// ---------- rendering ----------

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c !== null && c !== undefined) node.append(c);
  return node;
}

function render(res, elapsedPage) {
  results.textContent = '';
  const head = h('div', { class: 'run-head' },
    h('h2', { text: res.title || 'Untitled circuit' }),
    h('span', { class: 'muted', text: res.ok
      ? `${res.analyses.length} ${res.analyses.length === 1 ? 'analysis' : 'analyses'} · ${(elapsedPage / 1000).toFixed(2)} s`
      : `${(elapsedPage / 1000).toFixed(2)} s` }));
  results.appendChild(head);
  if (res.schematic) results.appendChild(renderDrawing(res.schematic));

  if (!res.ok) {
    const box = h('div', { class: 'error', role: 'alert' },
      h('strong', { text: 'Could not simulate. ' }), res.error.message);
    results.appendChild(box);
    if (res.error.detail) {
      results.appendChild(h('details', { class: 'more' }, h('summary', { text: 'Technical details' }),
        h('pre', { text: res.error.detail })));
    }
  } else {
    for (const a of res.analyses) results.appendChild(renderAnalysis(a));
    if (!res.analyses.length) {
      results.appendChild(h('p', { class: 'muted', text: 'The netlist ran but asked for no analyses. Add a line such as .op' }));
    }
  }
  if (res.console && res.console.trim()) {
    results.appendChild(h('details', { class: 'more' }, h('summary', { text: 'Messages from ahkab' }),
      h('pre', { text: res.console })));
  }
}

// The circuit as drawn by the schematic generator forked from Symbulator.
// The SVG is parsed as XML and imported, never assigned as HTML.
function renderDrawing(d) {
  if (d.svg) {
    const doc = new DOMParser().parseFromString(d.svg, 'image/svg+xml');
    const svg = doc.documentElement;
    if (svg.nodeName.toLowerCase() === 'svg') {
      svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', 'Circuit diagram');
      const frame = h('div', { class: 'schematic' }, document.importNode(svg, true));
      return card('Circuit', frame);
    }
    return card('Circuit', h('p', { class: 'muted', text: 'The drawing could not be displayed.' }));
  }
  const message = d.message || d.error || 'The circuit could not be drawn.';
  return card('Circuit', h('p', { class: 'muted', text: message }));
}

function card(title, ...body) {
  return h('section', { class: 'card' }, h('h3', { text: title }), ...body);
}

function table(headers, rows, opts = {}) {
  const t = h('table', { class: opts.className || '' });
  const tr = h('tr');
  headers.forEach((label, i) => tr.appendChild(h('th', { text: label, class: opts.numeric && opts.numeric[i] ? 'num' : '' })));
  t.appendChild(h('thead', {}, tr));
  const body = h('tbody');
  for (const r of rows) {
    const row = h('tr');
    r.forEach((cell, i) => {
      const td = h('td', { class: opts.numeric && opts.numeric[i] ? 'num' : '' });
      if (cell instanceof Node) td.appendChild(cell); else td.textContent = cell;
      row.appendChild(td);
    });
    body.appendChild(row);
  }
  t.appendChild(body);
  return h('div', { class: 'table-wrap' }, t);
}

function renderAnalysis(a) {
  if (a.type === 'op') {
    return card(a.title,
      table(['Variable', 'Value', 'Exact'], a.rows.map((r) => [r.name, eng(r.value, r.unit), r.value === null ? '—' : String(r.value)]),
        { numeric: [false, true, true] }),
      h('details', { class: 'more' }, h('summary', { text: 'Full report, including each element' }), h('pre', { text: a.report })));
  }
  if (a.type === 'pz') {
    const rows = a.rows.map((r) => [r.kind === 'pole' ? 'Pole' : 'Zero', r.name, eng(r.re, ''), eng(r.im, ''), r.unit]);
    return card(a.title + (a.rows.length ? '' : ' — none found'),
      table(['Kind', 'Name', 'Real', 'Imaginary', 'Unit'], rows, { numeric: [false, false, true, true, false] }));
  }
  if (a.type === 'symbolic') {
    const parts = [table(['Variable', 'Expression'], a.rows.map((r) => [r.name, h('code', { text: r.expr })]), { className: 'symbolic' })];
    if (a.transfer_functions.length) {
      parts.push(h('h4', { text: 'Transfer functions' }));
      parts.push(table(['Ratio', 'Gain', 'DC gain', 'Poles', 'Zeros'],
        a.transfer_functions.map((t) => [t.name, h('code', { text: t.gain }), h('code', { text: t.gain0 }),
          t.poles.join(', ') || '—', t.zeros.join(', ') || '—']), { className: 'symbolic' }));
    }
    return card(a.title, ...parts);
  }
  if (a.type === 'dc' || a.type === 'tran' || a.type === 'ac' || a.type === 'pss') return renderSweep(a);
  return card(a.title, h('pre', { text: a.text }));
}

function defaultSelection(a) {
  const names = a.series.map((s) => s.name);
  const requested = [];
  for (const p of a.plot_requests || []) {
    // .plot names ahkab accepts: V(2), V2, I(V1)... match loosely.
    const want = p.y2.replace(/^V\((\w+)\)$/, 'V$1');
    const hit = names.find((n) => n.toUpperCase() === want);
    if (hit && !requested.includes(hit)) requested.push(hit);
  }
  if (requested.length) return requested.slice(0, PALETTE_SIZE);
  const voltages = names.filter((n) => /^V/i.test(n) && !/^I\(/i.test(n));
  return (voltages.length ? voltages : names).slice(0, 4);
}

function renderSweep(a) {
  const section = card(a.title);
  const note = [];
  note.push(`${a.points} points`);
  if (a.thinned) note.push(`showing ${a.x.values.length}`);
  section.appendChild(h('p', { class: 'muted small', text: note.join(' · ') }));

  const chosen = defaultSelection(a);
  const slotOf = new Map();
  const assign = (name) => {
    if (slotOf.has(name)) return;
    const used = new Set(slotOf.values());
    for (let i = 1; i <= PALETTE_SIZE; i++) if (!used.has(i)) { slotOf.set(name, i); return; }
  };
  chosen.forEach(assign);

  const picker = h('fieldset', { class: 'picker' }, h('legend', { text: 'Show' }));
  const limit = h('span', { class: 'muted small limit', text: '' });
  const charts = h('div', { class: 'charts' });
  const tableHolder = h('details', { class: 'more' }, h('summary', { text: 'Data table' }));

  for (const s of a.series) {
    const id = `s-${Math.random().toString(36).slice(2)}`;
    const box = h('input', { type: 'checkbox', id });
    box.checked = chosen.includes(s.name);
    box.addEventListener('change', () => {
      if (box.checked) {
        if (slotOf.size >= PALETTE_SIZE) { box.checked = false; limit.textContent = `At most ${PALETTE_SIZE} at once.`; return; }
        assign(s.name);
      } else {
        slotOf.delete(s.name);
      }
      limit.textContent = '';
      draw();
    });
    picker.appendChild(h('label', { for: id }, box, ` ${s.name}`, h('span', { class: 'muted', text: s.unit ? ` [${s.unit}]` : '' })));
  }
  picker.appendChild(limit);
  section.append(picker, charts, tableHolder);

  const colorOf = (name) => `var(--series-${slotOf.get(name)})`;

  function draw() {
    charts.textContent = '';
    const shown = a.series.filter((s) => slotOf.has(s.name));
    if (!shown.length) {
      charts.appendChild(h('p', { class: 'muted', text: 'Tick a variable above to plot it.' }));
    }
    const units = [...new Set(shown.map((s) => s.unit))];
    for (const unit of units) {
      const group = shown.filter((s) => s.unit === unit);
      const quantity = unit === 'V' ? 'Voltage' : unit === 'A' ? 'Current' : 'Value';
      if (a.complex) {
        const mag = h('div'), phase = h('div');
        charts.append(h('h4', { text: `${quantity}: magnitude` }), mag, h('h4', { text: `${quantity}: phase` }), phase);
        lineChart(mag, { x: a.x, series: group.map((s) => ({ name: s.name, values: s.db, color: colorOf(s.name) })),
          yLabel: 'Magnitude', yUnit: unit ? `dB${unit}` : 'dB', ariaLabel: `${quantity} magnitude against ${a.x.name}` });
        lineChart(phase, { x: a.x, series: group.map((s) => ({ name: s.name, values: s.phase, color: colorOf(s.name) })),
          yLabel: 'Phase', yUnit: '°', ariaLabel: `${quantity} phase against ${a.x.name}` });
      } else {
        const holder = h('div');
        charts.append(h('h4', { text: quantity }), holder);
        lineChart(holder, { x: a.x, series: group.map((s) => ({ name: s.name, values: s.values, color: colorOf(s.name) })),
          yLabel: quantity, yUnit: unit, ariaLabel: `${quantity} against ${a.x.name}` });
      }
    }
    tableHolder.dataset.dirty = '1';
    if (tableHolder.open) fillTable();
  }

  function fillTable() {
    if (tableHolder.dataset.dirty !== '1') return;
    tableHolder.dataset.dirty = '';
    for (const old of tableHolder.querySelectorAll('.table-wrap')) old.remove();
    const shown = a.series.filter((s) => slotOf.has(s.name));
    const headers = [`${a.x.name}${a.x.unit ? ' [' + a.x.unit + ']' : ''}`];
    const cols = [];
    for (const s of shown) {
      if (a.complex) {
        headers.push(`|${s.name}| [dB]`, `∠${s.name} [°]`);
        cols.push(s.db, s.phase);
      } else {
        headers.push(`${s.name}${s.unit ? ' [' + s.unit + ']' : ''}`);
        cols.push(s.values);
      }
    }
    const rows = a.x.values.map((xv, i) => [xv === null ? '—' : String(xv), ...cols.map((c) => (c[i] === null ? '—' : String(c[i])))]);
    tableHolder.appendChild(table(headers, rows, { numeric: headers.map(() => true), className: 'data' }));
  }
  tableHolder.addEventListener('toggle', () => { if (tableHolder.open) fillTable(); });

  draw();
  return section;
}

loadExamples();
