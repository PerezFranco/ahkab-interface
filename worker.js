// An interface for ahkab -- the Web Worker that runs Python.
//
// Copyright 2026 Roberto Perez-Franco
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Python runs here, off the page's main thread, so the page stays responsive
// while libraries load and while circuits simulate. Messages in:
//   {type: 'run', id, netlist}
// Messages out:
//   {type: 'status', stage}                 loading progress
//   {type: 'ready', timings}                ahkab can simulate
//   {type: 'deferred', state, seconds?}     SymPy and scipy.signal, loaded after 'ready'
//   {type: 'result', id, result}            engine.run() output
//   {type: 'fatal', message}                start-up failed

// A module worker: importScripts() of the classic pyodide.js failed to load
// in testing, while the ES module loads cleanly.
import { loadPyodide } from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';
const WHEELS = ['tabulate-0.10.0-py3-none-any.whl', 'ahkab-0.18-py3-none-any.whl'];
const HOME = '/opt/interface';


const base = new URL('./', self.location.href).href;
const now = () => performance.now();
let engine = null;
const pending = [];

function post(type, data) {
  self.postMessage(Object.assign({ type }, data || {}));
}

async function fetchBytes(path) {
  // no-store: the wheels keep the same file name across rebuilds, and a
  // cached copy would silently run the previous ahkab.
  const response = await fetch(base + path, { cache: 'no-store' });
  if (!response.ok) throw new Error(path + ': HTTP ' + response.status);
  return new Uint8Array(await response.arrayBuffer());
}

function runOne(msg) {
  let result;
  try {
    result = JSON.parse(engine.run_json(msg.netlist));
  } catch (err) {
    result = { ok: false, title: '', error: { kind: 'internal',
      message: 'The interface failed while running this circuit.', detail: String(err && err.stack || err) } };
  }
  post('result', { id: msg.id, result });
}

self.onmessage = (event) => {
  const msg = event.data;
  if (msg.type !== 'run') return;
  if (engine) runOne(msg); else pending.push(msg);
};

(async () => {
  const t0 = now();
  const timings = {};
  try {
    post('status', { stage: 'runtime' });
    const pyodide = await loadPyodide({ indexURL: PYODIDE });
    timings.runtime = now() - t0;

    post('status', { stage: 'packages' });
    let t = now();
    await pyodide.loadPackage(['numpy', 'scipy', 'sympy', 'micropip']);
    timings.packages = now() - t;

    post('status', { stage: 'engine' });
    t = now();
    pyodide.FS.mkdirTree(HOME + '/wheels');
    for (const wheel of WHEELS) {
      pyodide.FS.writeFile(HOME + '/wheels/' + wheel, await fetchBytes('vendor/' + wheel));
    }
    pyodide.FS.writeFile(HOME + '/engine.py', await fetchBytes('engine.py'));
    const list = WHEELS.map((w) => "'emfs:" + HOME + '/wheels/' + w + "'").join(', ');
    await pyodide.runPythonAsync('import micropip\nawait micropip.install([' + list + '], deps=False)');
    pyodide.runPython("import sys\nif '" + HOME + "' not in sys.path: sys.path.insert(0, '" + HOME + "')");
    const module = pyodide.pyimport('engine');
    timings.install = now() - t;
    timings.warm = module.warm() * 1000;
    timings.total = now() - t0;
    engine = module;
    post('ready', { timings });

    while (pending.length) runOne(pending.shift());

    // Everything else loads now, in the background. A run requested while
    // this is under way waits for it to finish.
    post('deferred', { state: 'loading' });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const seconds = engine.load_deferred();
    post('deferred', { state: 'ready', seconds });
  } catch (err) {
    post('fatal', { message: String(err && err.message || err), detail: String(err && err.stack || '') });
  }
})();
