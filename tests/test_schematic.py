# Tests for netlist_schematic.py and the forked generator, run natively.
#
# Copyright 2026 Roberto Perez-Franco
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Run from the interface folder:  ..\.venv\Scripts\python.exe -m pytest tests -q

import contextlib
import glob
import io
import os
import re
import sys

import pytest

sys.modules['matplotlib'] = None
sys.modules['pylab'] = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import netlist_schematic as ns  # noqa: E402
from ahkab import netlist_parser  # noqa: E402

AHKAB_TESTS = os.path.join(ROOT, '..', 'ahkab', 'tests')


def parse(path):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        circ, _, _ = netlist_parser.parse_circuit(os.path.abspath(path))
    return circ


def parse_text(text, tmp_path):
    p = tmp_path / 'c.ckt'
    p.write_text(text)
    return parse(str(p))


def labels(svg):
    return [re.sub(r'<[^>]+>', '', t) for t in re.findall(r'<text[^>]*>(.*?)</text>', svg, re.S)]


def test_ohms_law_description_and_labels():
    circ = parse(os.path.join(ROOT, 'examples', 'ohms_law.ckt'))
    t = ns.Translation(circ)
    assert t.description == 'e__v1,supply,0,5:r__ra,supply,0,100:r__rb,supply,0,1k'
    shown = labels(ns.draw(circ)['svg'])
    # The fork shows ahkab's names: V1, RA, RB -- never E_V1 or R_RA.
    assert 'V1' in shown and 'RA' in shown and 'RB' in shown
    assert not any('E' in s and 'V1' in s for s in shown)
    assert 'supply' in shown and '5 V' in shown and '1k Ω' in shown


def test_si_shorthand():
    assert ns.si(1500) == '1.5k'
    assert ns.si(1.5e-5) == '15u'
    assert ns.si(550e-12) == '550p'
    assert ns.si(0.3e3) == '300'
    assert ns.si(1e20) == '1e+20'
    assert ns.si(0) == '0'


def test_dependent_sources_keep_ahkab_conventions(tmp_path):
    # Every mapping below was checked by solving the same circuit in ahkab
    # and in Symbulator: no sign changes are needed.
    circ = parse_text(
        'deps\n'
        'v1 1 0 type=vdc vdc=1\n'
        'ra 1 2 1k\n'
        'rb 2 0 1k\n'
        'e1 3 0 2 0 2\n'        # VCVS across rb, which sits exactly on (2, 0)
        'rl1 3 0 1k\n'
        'g1 4 0 0 2 1m\n'       # VCCS sensing (0, 2): rb reversed
        'rl2 4 0 1k\n'
        'f1 0 5 v1 3\n'         # CCCS sensing v1's current
        'rl3 5 0 1k\n'
        'h1 6 0 v1 50\n'        # CCVS
        'rl4 6 0 1k\n'
        'e2 7 0 1 2 1\n'        # VCVS sensing (1, 2): ra
        'rl5 7 0 1k\n'
        '.op\n', tmp_path)
    lines = ns.Translation(circ).description.split(':')
    by_name = {l.split(',')[0]: l for l in lines}
    assert by_name['e__e1'] == 'e__e1,3,0,2*vr__rb'
    assert by_name['j__g1'] == 'j__g1,4,0,0.001*(-vr__rb)'
    assert by_name['j__f1'] == 'j__f1,0,5,3*ie__v1'
    assert by_name['e__h1'] == 'e__h1,6,0,50*ie__v1'
    assert by_name['e__e2'] == 'e__e2,7,0,1*vr__ra'


def test_control_by_node_voltages_when_no_element_spans_them(tmp_path):
    circ = parse_text('n\nv1 1 0 type=vdc vdc=1\nr1 1 2 1k\nr2 2 3 1k\nr3 3 0 1k\n'
                      'e1 4 0 1 3 5\nrl 4 0 1k\n.op\n', tmp_path)
    by_name = {l.split(',')[0]: l for l in ns.Translation(circ).description.split(':')}
    assert by_name['e__e1'] == 'e__e1,4,0,5*(v1-v3)'


def test_sources_are_labelled_by_what_they_are(tmp_path):
    circ = parse_text('s\nv1 1 0 type=vdc vdc=0 type=vac vac=2\nr1 1 0 1k\n'
                      'v2 2 0 type=pulse v1=0 v2=1 td=0 tr=1n tf=1n pw=1n per=10n\nr2 2 0 1k\n.op\n',
                      tmp_path)
    by_name = {l.split(',')[0]: l for l in ns.Translation(circ).description.split(':')}
    assert by_name['e__v1'].endswith(',AC 2')
    assert by_name['e__v2'].endswith(',pulse')


def test_coupled_inductors_draw_without_symbulators_solver():
    path = os.path.join(AHKAB_TESTS, 'transformer', 'transformer.ckt')
    if not os.path.exists(path):
        pytest.skip('ahkab clone not beside the interface')
    result = ns.draw(parse(path))
    assert 'svg' in result, result
    assert 'm__k,l__l1,l__l2,k=0.99999' in result['description']
    assert not any(m in sys.modules for m in ('schematic.engine', 'schematic.laplace', 'schematic.analysis'))


def test_subcircuit_names_are_made_legal(tmp_path):
    circ = parse_text('x\n.subckt div a b\nr1 a m 1k\nr2 m b 1k\n.ends\n'
                      'v1 1 0 type=vdc vdc=1\nx1 name=div a=1 b=0\n.op\n', tmp_path)
    t = ns.Translation(circ)
    for line in t.description.split(':'):
        assert line.split(',')[0].isidentifier(), line
    assert 'svg' in ns.draw(circ)


def test_unsupported_elements_are_reported_not_drawn():
    for name, kind in (('mosfet_op.ckt', 'MOSFETs'), ('diode_op.ckt', 'diodes')):
        result = ns.draw(parse(os.path.join(ROOT, 'examples', name)))
        assert 'svg' not in result
        assert kind in result['message']


def test_every_linear_ahkab_test_circuit_draws():
    paths = sorted(glob.glob(os.path.join(AHKAB_TESTS, '*', '*.ckt')))
    if not paths:
        pytest.skip('ahkab clone not beside the interface')
    drawn = 0
    for path in paths:
        try:
            circ = parse(path)
        except Exception:
            continue  # a few test netlists do not parse at all; see HANDOVER-2.md
        result = ns.draw(circ)
        if 'unsupported' in result:
            continue
        assert 'svg' in result, (path, result)
        drawn += 1
    assert drawn >= 25
