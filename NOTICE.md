# Notices

## ahkab

The simulation engine is **ahkab**, by Giuseppe Venturini and contributors,
© 2006–2015, distributed under the GNU General Public License, version 2.
Upstream: <https://github.com/ahkab/ahkab>

### This page ships a modified ahkab

`vendor/ahkab-0.18-py3-none-any.whl` is built from Roberto Perez-Franco's
maintenance fork, <https://github.com/PerezFranco/ahkab>, not from the 0.18
release. `vendor/AHKAB_SOURCE.txt` records the exact branch and commit.

Changes made in 2026 by Roberto Perez-Franco, relative to upstream `master`
(`1e89391`), each proposed back to ahkab:

1. Restore compatibility with modern Python and SciPy — ahkab/ahkab#84
2. Fix latent bugs exposed by modern NumPy, including MOSFET operating points — ahkab/ahkab#85
3. Port the test suite off nose — ahkab/ahkab#86
4. Support NumPy 2 — ahkab/ahkab#87
5. Fix unicode output on Windows — ahkab/ahkab#88
6. Import SymPy and scipy.signal only when they are needed — branch
   `lazy-imports`, not yet submitted

Each change's reasoning is in its commit message on the fork.

### Example circuits

Every netlist in `examples/` is copied unchanged from ahkab's own test suite
(`tests/` in the ahkab repository), by Giuseppe Venturini and contributors,
GPL-2.0.

## The interface

Everything else in this repository — `index.html`, `app.js`, `chart.js`,
`worker.js`, `engine.py`, `style.css`, `tests/`, `tools/` — is © 2026 Roberto
Perez-Franco, free software under the GNU General Public License, version 2 or
(at your option) any later version. See `COPYING`.

## Loaded or bundled third-party software

| Component | Licence | How it arrives |
|---|---|---|
| [Pyodide](https://pyodide.org) 314.0.7, including micropip 0.11.1 | MPL-2.0 | loaded from jsDelivr |
| NumPy 2.4.6 | BSD-3-Clause | loaded with Pyodide |
| SciPy 1.18.0 | BSD-3-Clause | loaded with Pyodide |
| SymPy 1.14.0, with mpmath 1.4.1 | BSD-3-Clause | loaded with Pyodide |
| tabulate 0.10.0 | MIT | `vendor/tabulate-0.10.0-py3-none-any.whl` |
