# An interface for ahkab -- the Python side, run inside Pyodide.
#
# Copyright 2026 Roberto Perez-Franco
# SPDX-License-Identifier: GPL-2.0-or-later
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version. See COPYING.
"""Run a netlist through ahkab and return its results as plain data.

The simulation engine is ahkab, by Giuseppe Venturini. This module only
drives it: it writes the netlist to a scratch directory, calls
``ahkab.main``, and converts each analysis result into lists, numbers and
strings the page can draw. It runs unchanged in CPython, which is how
tests/test_engine.py exercises it.
"""

import contextlib
import copy
import io
import math
import os
import shutil
import tempfile
import time
import traceback

_state = {'options': None, 'plot_requests': []}

# Sweeps longer than this are thinned before being sent to the page. A line
# chart a few hundred pixels wide cannot show more, and the page says when
# it happened.
MAX_POINTS = 4000


def warm():
    """Import ahkab and prepare it for repeated runs in one process.

    Returns the time taken in seconds. Deliberately does not import SymPy
    or scipy.signal: those are loaded by :func:`load_deferred`, so the page
    can start simulating before they are ready.
    """
    t0 = time.perf_counter()
    import ahkab  # noqa: F401
    from ahkab import options, plotting

    # ahkab draws .plot directives with Matplotlib, which the browser does
    # not have. Record what was asked for instead, and let the page draw it.
    def plot_results(title, y2y1_list, results, outfilename=None):
        _state['plot_requests'].append((id(results), list(y2y1_list)))
    plotting.plot_results = plot_results
    plotting.show_plots = lambda: None

    # ahkab keeps configuration in module-level state that a netlist can
    # change; restore it before every run so one circuit cannot leak into
    # the next.
    _state['options'] = {k: copy.deepcopy(v) for k, v in vars(options).items()
                         if not k.startswith('__') and not callable(v)
                         and not isinstance(v, type(os))}
    return time.perf_counter() - t0


def load_deferred():
    """Import what only some analyses need. Returns the time taken."""
    t0 = time.perf_counter()
    import sympy                 # noqa: F401  symbolic analysis
    import scipy.signal.windows  # noqa: F401  .fft windowing
    import netlist_schematic     # noqa: F401  the drawing
    from schematic import schematic  # noqa: F401
    return time.perf_counter() - t0


def _draw(path):
    """The circuit drawing for the netlist at ``path``, or None when the
    netlist does not parse (the simulation reports that itself)."""
    from ahkab import netlist_parser
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            circ, _, _ = netlist_parser.parse_circuit(path)
    except Exception:
        return None
    try:
        import netlist_schematic
        return netlist_schematic.draw(circ)
    except Exception as e:  # a drawing problem must never cost the simulation
        return {'error': 'The drawing could not be made: %s: %s' % (type(e).__name__, e)}


def _restore_options():
    from ahkab import options
    for k, v in _state['options'].items():
        setattr(options, k, copy.deepcopy(v))


def _num(x):
    """A finite float, or None -- JSON has no NaN or infinity."""
    x = float(x)
    return x if math.isfinite(x) else None


def _thin(n):
    """Indices that keep at most MAX_POINTS samples, always the last one."""
    if n <= MAX_POINTS:
        return None
    step = math.ceil(n / MAX_POINTS)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return idx


def _is_log_spaced(x):
    if len(x) < 3 or any(v is None or v <= 0 for v in x):
        return False
    r0 = x[1] / x[0]
    if r0 <= 1.0:
        return False
    return all(abs((x[i + 1] / x[i]) / r0 - 1.0) < 1e-6 for i in range(len(x) - 1))


def _capture_text(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def _convert_op(sol):
    import numpy as np
    arr = np.asarray(sol.asarray()).reshape(len(sol.variables), -1)
    rows = [{'name': name, 'value': _num(arr[i, 0]), 'unit': sol.units.get(name, '')}
            for i, name in enumerate(sol.variables)]
    report = _capture_text(lambda: sol.write_to_file(filename='stdout'))
    return {'type': 'op', 'title': 'Operating point', 'rows': rows, 'report': report}


def _convert_sweep(kind, sol, requests):
    import numpy as np
    names = list(sol.variables)
    arr = np.asarray(sol.asarray())
    x_all = arr[0].real
    idx = _thin(len(x_all))
    pick = (lambda a: a) if idx is None else (lambda a: a[idx])
    x = [_num(v) for v in pick(x_all)]
    series = []
    for i in range(1, len(names)):
        name = names[i]
        data = pick(arr[i])
        entry = {'name': name, 'unit': sol.units.get(name, '')}
        if np.iscomplexobj(data):
            mag = np.abs(data)
            with np.errstate(divide='ignore'):
                entry['db'] = [_num(v) for v in 20 * np.log10(mag)]
            entry['phase'] = [_num(v) for v in np.degrees(np.angle(data))]
        else:
            entry['values'] = [_num(v) for v in data.real]
        series.append(entry)
    titles = {'dc': 'DC sweep', 'tran': 'Transient', 'ac': 'AC analysis',
              'pss': 'Periodic steady state'}
    xlabel = sol.get_xlabel() if hasattr(sol, 'get_xlabel') else names[0]
    plotted = []
    for y2, y1 in requests:
        plotted.append({'y2': str(y2).strip('|').upper(),
                        'y1': None if y1 is None else str(y1).strip('|').upper()})
    return {'type': kind, 'title': titles.get(kind, kind),
            'complex': bool(np.iscomplexobj(arr)),
            'x': {'name': xlabel, 'unit': sol.units.get(names[0], ''), 'values': x,
                  'log': _is_log_spaced(x)},
            'series': series, 'points': int(len(x_all)), 'thinned': idx is not None,
            'plot_requests': plotted}


def _convert_pz(sol):
    import numpy as np
    rows = []
    for name in sol.variables:
        v = complex(np.asarray(sol[name]).ravel()[0])
        rows.append({'name': name, 'kind': 'pole' if name[0] == 'p' else 'zero',
                     're': _num(v.real), 'im': _num(v.imag),
                     'unit': sol.units.get(name, '')})
    return {'type': 'pz', 'title': 'Poles and zeros', 'rows': rows}


def _convert_symbolic(value):
    sol, tfs = value
    rows = [{'name': str(k), 'expr': str(v)} for k, v in sol.items()]
    tf_rows = []
    if tfs:
        for k, v in tfs.items():
            tf_rows.append({'name': str(k), 'gain': str(v['gain']),
                            'gain0': str(v['gain0']),
                            'poles': [str(p) for p in v['poles']],
                            'zeros': [str(z) for z in v['zeros']]})
    return {'type': 'symbolic', 'title': 'Symbolic analysis', 'rows': rows,
            'transfer_functions': tf_rows}


def run(netlist):
    """Simulate ``netlist``, the text of an ahkab netlist.

    Always returns a dict with ``ok``. On failure, ``error['message']`` says
    what went wrong in a sentence meant for the person who wrote the netlist.
    """
    import ahkab
    from ahkab import netlist_parser, circuit

    if _state['options'] is None:
        warm()
    _restore_options()
    _state['plot_requests'] = []
    title = next((l.strip() for l in netlist.splitlines() if l.strip()), '')
    workdir = tempfile.mkdtemp(prefix='ahkab-')
    path = os.path.join(workdir, 'circuit.ckt')
    with open(path, 'w', encoding='utf-8') as fp:
        fp.write(netlist if netlist.endswith('\n') else netlist + '\n')
    drawing = _draw(path)
    out = io.StringIO()
    t0 = time.perf_counter()
    try:
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                results = ahkab.main(path, outfile=os.path.join(workdir, 'out'), verbose=0)
        except netlist_parser.NetlistParseError as e:
            drawing = None
            message = 'The netlist could not be read: %s' % e
            if 'unknown type' in str(e) and 'source' in str(e):
                # The commonest cause: a source line pasted from SPICE.
                message += ('. ahkab writes sources with type=, for example '
                            '"v1 1 0 type=vdc vdc=5" or "v1 1 0 type=vac vac=1", '
                            'where SPICE writes "V1 1 0 DC 5" or "V1 1 0 AC 1".')
            return _failure('parse', message, out, t0, title)
        except circuit.CircuitError as e:
            return _failure('circuit', 'The circuit is not valid: %s' % e, out, t0, title,
                            drawing=drawing)
        except Exception as e:  # ahkab raises many kinds; report, don't crash
            return _failure('simulation', 'The simulation failed: %s: %s'
                            % (type(e).__name__, e), out, t0, title,
                            detail=traceback.format_exc(), drawing=drawing)
        elapsed = time.perf_counter() - t0
        try:
            requests = {}
            for rid, pairs in _state['plot_requests']:
                requests.setdefault(rid, []).extend(pairs)
            analyses = []
            for kind, value in (results or {}).items():
                if kind == 'op':
                    analyses.append(_convert_op(value))
                elif kind in ('dc', 'tran', 'ac', 'pss'):
                    analyses.append(_convert_sweep(kind, value, requests.get(id(value), [])))
                elif kind == 'pz':
                    analyses.append(_convert_pz(value))
                elif kind == 'symbolic':
                    analyses.append(_convert_symbolic(value))
                else:
                    analyses.append({'type': 'text', 'title': str(kind), 'text': str(value)})
            for a in analyses:  # the scratch path means nothing to the reader
                if 'report' in a:
                    a['report'] = a['report'].replace(path, 'the netlist above')
            lis = os.path.join(workdir, 'out.lis')
            if os.path.exists(lis):
                with open(lis, encoding='utf-8') as fp:
                    analyses.append({'type': 'text', 'title': 'FFT', 'text': fp.read()})
        except Exception as e:
            return _failure('display', 'The simulation ran, but its results could not be '
                            'prepared for display: %s: %s' % (type(e).__name__, e),
                            out, t0, title, detail=traceback.format_exc(), drawing=drawing)
        return {'ok': True, 'title': title, 'elapsed_s': elapsed,
                'analyses': analyses, 'console': out.getvalue(), 'schematic': drawing}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_json(netlist):
    """:func:`run`, serialised as strict JSON for the page."""
    import json
    return json.dumps(run(netlist), allow_nan=False)


def _failure(kind, message, out, t0, title, detail=None, drawing=None):
    return {'ok': False, 'title': title, 'elapsed_s': time.perf_counter() - t0,
            'error': {'kind': kind, 'message': message, 'detail': detail},
            'console': out.getvalue(), 'schematic': drawing}
