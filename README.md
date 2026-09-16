# An interface for ahkab

A web page for simulating circuits with **ahkab**, the SPICE-like circuit
simulator by Giuseppe Venturini. Write or paste an ahkab netlist, press Run,
and see the operating point, sweeps, transients, AC responses, poles and zeros,
and symbolic results as tables and charts.

Python runs in the visitor's browser through [Pyodide](https://pyodide.org). The
server only serves static files, and nothing typed into the page leaves the
browser.

This is **an** interface for ahkab, not an official part of the ahkab project.

## Run it locally

From this folder, with the project's virtual environment:

```text
..\.venv\Scripts\python.exe -m http.server 8766 --bind 127.0.0.1
```

then open <http://127.0.0.1:8766/>. It must be served over HTTP; opening
`index.html` as a file does not work, because the page starts a Web Worker and
fetches the wheels. The first load downloads Pyodide from jsDelivr.

## Test

```text
..\.venv\Scripts\python.exe -m pytest tests -q
```

The tests drive `engine.py` natively with Matplotlib blocked, so they see what
the browser sees.

## Rebuild the ahkab wheel

```text
bash tools/build-ahkab-wheel.sh lazy-imports
```

Builds from the sibling `..\ahkab` clone and records the commit in
`vendor/AHKAB_SOURCE.txt`.

## How it fits together

| File | Role |
|---|---|
| `index.html`, `style.css` | the page |
| `app.js` | editor, examples, and rendering of results |
| `chart.js` | SVG line charts with a hover readout |
| `worker.js` | Web Worker: loads Pyodide and ahkab, runs circuits |
| `engine.py` | Python: runs ahkab and turns its results into plain data |
| `examples/` | netlists from ahkab's own test suite |
| `vendor/` | the ahkab and tabulate wheels |

Start-up happens in two stages. The page can simulate as soon as NumPy, SciPy
and ahkab are loaded. SymPy (symbolic analysis) and scipy.signal (FFT windows)
then load in the background; a symbolic or FFT run requested before they
finish waits for them.

## Before publishing

- [ ] The ahkab source the page ships must be publicly available: push the
      `lazy-imports` branch of the fork, or wait until it is merged.
- [ ] Publish this repository and link its source from the page footer.
- [ ] Check PythonAnywhere's static-file hosting details at the time.

## Licence

© 2026 Roberto Perez-Franco. Free software under the GNU General Public
License, version 2 or (at your option) any later version; see `COPYING`.
ahkab is © Giuseppe Venturini and contributors, GPL-2.0. See `NOTICE.md` for
the modified ahkab this page ships and for third-party components.
