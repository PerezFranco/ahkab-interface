# Tests for engine.py, run natively in CPython.
#
# Copyright 2026 Roberto Perez-Franco
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Matplotlib is blocked before ahkab is imported, because the browser build
# has none: these tests must see what the page will see.
#
# Run from the interface folder:  ..\.venv\Scripts\python.exe -m pytest tests -q

import json
import os
import sys

sys.modules['matplotlib'] = None
sys.modules['pylab'] = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import engine  # noqa: E402

EXAMPLES = os.path.join(ROOT, 'examples')


def netlist(name):
    with open(os.path.join(EXAMPLES, name), encoding='latin-1') as fp:
        return fp.read()


def run(name):
    res = engine.run(netlist(name))
    assert res['ok'], res.get('error')
    json.dumps(res, allow_nan=False)  # must be valid JSON for the page
    return res


def analysis(res, kind):
    found = [a for a in res['analyses'] if a['type'] == kind]
    assert found, 'no %s analysis in %s' % (kind, [a['type'] for a in res['analyses']])
    return found[0]


def op_value(res, name):
    return {r['name']: r['value'] for r in analysis(res, 'op')['rows']}[name]


def close(a, b, rel=1e-6, abs_=1e-12):
    return abs(a - b) <= abs_ + rel * abs(b)


def test_matplotlib_really_is_absent():
    import ahkab.ahkab as core
    engine.warm()
    assert core.plotting_available is False


def test_every_example_listed_and_runs():
    with open(os.path.join(EXAMPLES, 'examples.json'), encoding='utf-8') as fp:
        listed = {e['file'] for e in json.load(fp)['examples']}
    on_disk = {f for f in os.listdir(EXAMPLES) if f.endswith('.ckt')}
    assert listed == on_disk
    for name in sorted(listed):
        run(name)


def test_ohms_law():
    res = run('ohms_law.ckt')
    assert close(op_value(res, 'VSUPPLY'), 5.0)
    assert close(op_value(res, 'I(V1)'), -0.055)
    op = analysis(res, 'op')
    assert 'Total power dissipation' in op['report']


def test_dc_sweep_divider_and_plot_request():
    res = run('dc_sweep.ckt')
    dc = analysis(res, 'dc')
    x = dc['x']['values']
    assert len(x) == 51 and close(x[0], 0.0) and close(x[-1], 5.0, abs_=1e-9)
    assert dc['x']['log'] is False
    # The sweep variable is listed as V1 and so is node 1; the series must
    # still be the node voltages, in order.
    names = [s['name'] for s in dc['series']]
    assert names == ['V1', 'V2', 'I(V1)']
    v2 = dc['series'][1]['values']
    assert all(close(v, xv / 2, abs_=1e-9) for v, xv in zip(v2, x))  # 1k/1k divider
    assert {p['y2'] for p in dc['plot_requests']} == {'V2', 'V1'}


def test_series_resonance_ac_and_symbolic():
    res = run('series_resonance.ckt')
    ac = analysis(res, 'ac')
    assert ac['complex'] is True and ac['x']['log'] is True and len(ac['x']['values']) == 100
    s = ac['series'][0]
    assert 'db' in s and 'phase' in s and 'values' not in s
    sym = analysis(res, 'symbolic')
    exprs = {r['name']: r['expr'] for r in sym['rows']}
    assert 's' in exprs['I[L1]'] and 'L1' in exprs['I[L1]']


def test_rlc_pulse_transient():
    res = run('rlc_pulse.ckt')
    tran = analysis(res, 'tran')
    assert tran['points'] == len(tran['x']['values']) and not tran['thinned']
    assert tran['x']['unit'] == 's'
    assert all(v is not None for s in tran['series'] for v in s['values'])


def test_mosfet_operating_point_report():
    res = run('mosfet_op.ckt')
    op = analysis(res, 'op')
    assert 'ELEMENTS OP INFORMATION' in op['report']
    # The MOSFET's own operating point -- which no MOSFET circuit could
    # produce before PR #85 fixed the ragged drive-port voltages.
    assert 'm2 ch' in op['report'] and 'Ids' in op['report'] and 'gm' in op['report']
    assert 'ahkab-' not in op['report']  # no scratch-directory path leaks through
    assert close(op_value(res, 'V2'), 2.5)


def test_lowpass_poles_and_zeros_match_ahkab_reference():
    res = run('lowpass_pz.ckt')
    rows = analysis(res, 'pz')['rows']
    poles = [complex(r['re'], r['im']) for r in rows if r['kind'] == 'pole']
    zeros = [complex(r['re'], r['im']) for r in rows if r['kind'] == 'zero']
    # Reference values from ahkab's tests/pz_spice/test_pz_spice.py
    poles_ref = [-1.105884e-02 - 7.435365e-02j, -1.105884e-02 + 7.435365e-02j,
                 -1.882392e-02 - 1.418852e-01j, -1.882392e-02 + 1.418852e-01j,
                 -8.675361e-02 + 0j]
    zeros_ref = [-2.047019e-01j, -8.164476e-02j, 8.164476e-02j, 2.047019e-01j]
    for ref in poles_ref:
        assert any(abs(p - ref) <= 1e-4 + 1e-3 * abs(ref) for p in poles), ref
    for ref in zeros_ref:
        assert any(abs(z - ref) <= 1e-4 + 1e-3 * abs(ref) for z in zeros), ref


def test_sine_fft_report():
    res = run('sine_fft.ckt')
    analysis(res, 'tran')
    fft = [a for a in res['analyses'] if a['type'] == 'text' and a['title'] == 'FFT']
    assert fft and 'FFT components of transient response I(VS)' in fft[0]['text']


def test_spice_syntax_gives_a_readable_parse_error():
    res = engine.run('Pasted from SPICE\nVIN IN 0 AC 1\nR1 IN 0 1k\n.op\n')
    assert res['ok'] is False
    assert res['error']['kind'] == 'parse'
    assert 'unknown type ac' in res['error']['message']
    assert 'type=vac vac=1' in res['error']['message']  # the hint for SPICE syntax
    json.dumps(res, allow_nan=False)


def test_one_run_does_not_leak_into_the_next():
    first = run('dc_sweep.ckt')
    run('rlc_pulse.ckt')
    run('series_resonance.ckt')
    again = run('dc_sweep.ckt')
    a, b = analysis(first, 'dc'), analysis(again, 'dc')
    assert a['x'] == b['x'] and a['series'] == b['series']


def test_long_sweeps_are_thinned_but_keep_the_end(monkeypatch):
    monkeypatch.setattr(engine, 'MAX_POINTS', 100)
    res = run('rlc_pulse.ckt')
    tran = analysis(res, 'tran')
    assert tran['thinned'] is True and len(tran['x']['values']) <= 101
    monkeypatch.setattr(engine, 'MAX_POINTS', 10**9)
    unthinned = analysis(run('rlc_pulse.ckt'), 'tran')
    assert tran['x']['values'][-1] == unthinned['x']['values'][-1]


def test_deferred_load_is_really_deferred():
    import subprocess
    code = ("import sys; sys.modules['matplotlib']=None; sys.modules['pylab']=None; "
            "sys.path.insert(0, %r); import engine; engine.warm(); "
            "print('sympy' in sys.modules, 'scipy.signal' in sys.modules); "
            "engine.load_deferred(); "
            "print('sympy' in sys.modules, 'scipy.signal' in sys.modules)" % ROOT)
    out = subprocess.run([sys.executable, '-W', 'ignore', '-c', code],
                         capture_output=True, text=True, check=True).stdout.split('\n')
    lines = [l for l in out if l.startswith(('True', 'False'))]
    assert lines == ['False False', 'True True']


def test_run_json_is_strict_json():
    out = json.loads(engine.run_json(netlist('dc_sweep.ckt')))
    assert out['ok'] is True


def test_results_carry_the_drawing():
    res = run('dc_sweep.ckt')
    assert res['schematic']['svg'].startswith('<svg')


def test_a_drawing_problem_never_costs_the_simulation(monkeypatch):
    import netlist_schematic
    def broken(circ):
        raise RuntimeError('layout exploded')
    monkeypatch.setattr(netlist_schematic, 'draw', broken)
    res = run('ohms_law.ckt')
    assert res['ok'] is True
    assert 'layout exploded' in res['schematic']['error']


def test_no_drawing_for_a_netlist_that_does_not_parse():
    res = engine.run('Pasted from SPICE\nVIN IN 0 AC 1\nR1 IN 0 1k\n.op\n')
    assert res['ok'] is False and res['schematic'] is None
