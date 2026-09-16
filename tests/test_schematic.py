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
    class bjt_device(object):          # an element class the translator has never met
        part_id = 'q1'
        n1 = n2 = 0
    circ = parse(os.path.join(ROOT, 'examples', 'ohms_law.ckt'))
    circ.append(bjt_device())
    result = ns.draw(circ)
    assert 'svg' not in result
    assert result['unsupported'] == [{'part': 'q1', 'kind': 'bjt_device'}]
    assert 'bjt_device' in result['message']


# -- the nonlinear devices: diode, MOSFET, switch -----------------------------

from schematic import schematic as sc  # noqa: E402

NONLINEAR = ['bfpss1', 'colpitts', 'diode_mult', 'diode_op', 'diodecw8', 'downscaling_cm',
             'ekv1', 'ring3', 'ring3mosq', 'rout', 'shooting1', 'shooting/diffamp',
             'shooting/diffamp_bruteforce', 'switch1', 'symbro', 't1', 't1off', 't2',
             't2off', 't3', 't3n', 't3np', 't3p']


def test_diode_is_anode_then_cathode_and_labelled_by_its_model():
    circ = parse(os.path.join(ROOT, 'examples', 'diode_op.ckt'))
    by_name = {l.split(',')[0]: l for l in ns.Translation(circ).description.split(':')}
    assert by_name['d__d1'] == 'd__d1,2,0,di'            # ahkab: n1 anode, n2 cathode
    el = [e for e in sc.parse_circuit(ns.Translation(circ).description, expand_si=False)
          if e.kind == 'd'][0]
    assert (el.n1, el.n2, el.value, el.nodes) == ('2', '0', 'di', ['2', '0'])
    svg = ns.draw(circ)['svg']
    assert 'D' in labels(svg) or any('D' in s for s in labels(svg))


def test_mosfet_terminals_and_channel_type(tmp_path):
    circ = parse_text('mos\n'
                      'v1 d 0 type=vdc vdc=5\nv2 g 0 type=vdc vdc=1\nv3 s 0 type=vdc vdc=0\n'
                      'v4 b 0 type=vdc vdc=-1\n'
                      'm1 d g s b nch w=2u l=1u\n'       # mosq model, n-channel
                      'm2 s g d b pch w=1u l=3u\n'       # ekv model, p-channel
                      '.model mosq nch TYPE=n VTO=.4 KP=40e-6\n'
                      '.model ekv pch TYPE=p VTO=-.4 KP=12e-6\n.op\n', tmp_path)
    by_name = {l.split(',')[0]: l for l in ns.Translation(circ).description.split(':')}
    # ahkab's order, checked in mosq.py/ekv.py: n1 drain, ng gate, n2 source, nb bulk
    assert by_name['n__m1'] == 'n__m1,d,g,s,b,nch 2µ/1µ'
    assert by_name['p__m2'] == 'p__m2,s,g,d,b,pch 1µ/3µ'
    els = {e.name: e for e in sc.parse_circuit(ns.Translation(circ).description,
                                               expand_si=False)}
    m1 = els['n__m1']
    assert (m1.n1, m1.gate, m1.n2, m1.bulk) == ('d', 'g', 's', 'b')   # n2 is the source
    assert m1.nodes == ['d', 'g', 's', 'b']
    svg = ns.draw(circ)['svg']
    assert svg.count('scale(1,-1)') <= 2 and 'M' in ''.join(labels(svg))


def layout(desc):
    return sc._Layout(sc.parse_circuit(desc, expand_si=False))


def test_mosfet_bulk_tied_to_source_or_wired_elsewhere():
    tied = layout('e__vin,in,0,1:n__m1,d,in,0,0,nch:r__rd,d,dd,10k:e__vdd,dd,0,5')
    assert tied.mos['n__m1']['tied'] and tied.mos['n__m1']['bulk'] is None
    assert tied.mos['n__m1']['vertical'] and tied.mos['n__m1']['gate']['route'] == 'stub'
    # source live and bulk grounded: a horizontal body, bulk dropped to the rail
    to_rail = layout('e__vdd,dd,0,5:r__rd,dd,d,10k:n__m1,d,g,s,0,nch:r__rs,s,0,1k:e__vg,g,0,2')
    plan = to_rail.mos['n__m1']
    assert not plan['vertical'] and not plan['tied']
    assert plan['bulk']['route'] == 'rail' and plan['gate']['route'] == 'lane'
    # bulk to a live node of its own
    elsewhere = layout('e__vdd,dd,0,5:r__rd,dd,d,10k:n__m1,d,g,0,b,nch:e__vg,g,0,2:e__vb,b,0,-1')
    plan = elsewhere.mos['n__m1']
    assert plan['vertical'] and plan['bulk']['node'] == 'b' and plan['bulk']['route'] == 'lane'
    for desc in (tied, to_rail, elsewhere):
        assert '<svg' in sc._render(desc.elements)


def test_mosfet_grounded_gate_drops_to_the_rail():
    lay = layout('e__vdd,dd,0,5:p__m1,d,0,dd,dd,pch:r__rd,d,0,1k')
    assert lay.mos['p__m1']['gate'] == {'node': '0', 'side': 'D', 'route': 'rail',
                                        'col': lay.mos_cols[('p__m1', 'C')]}


def test_switch_control_is_marked_like_a_dependent_source():
    circ = parse(os.path.join(AHKAB_TESTS, 'switch1', 'switch1.ckt'))
    by_name = {l.split(',')[0]: l for l in ns.Translation(circ).description.split(':')}
    assert by_name['w__s1'] == 'w__s1,dd,out,dd,in,(vdd-vin)'   # n1, n2, then sn1, sn2
    assert by_name['w__s2'] == 'w__s2,out,0,in,0,ve__v1'         # v1 sits exactly on (in, 0)
    svg = ns.draw(circ)['svg']
    assert 'class="refk"' in svg          # the + / - a control puts on what it reads
    # with no control written, the switch is labelled by its sensing pair
    el = sc.parse_circuit('e__v1,a,0,1:w__s1,a,b,c,0:r__r1,b,0,1:r__r2,c,0,1',
                          expand_si=False)[1]
    assert el.control_nodes == ('c', '0') and el.nodes == ['a', 'b']
    assert sc._pretty(el) == 'vc'


def test_nonlinear_ahkab_test_circuits_draw_without_faults():
    last = {}
    orig = sc._Canvas.flush

    def hooked(self):
        last['cv'] = self
        orig(self)
    sc._Canvas.flush = hooked
    try:
        for name in NONLINEAR:
            parts = name.split('/')
            path = os.path.join(AHKAB_TESTS, parts[0], parts[-1] + '.ckt')
            if not os.path.exists(path):
                pytest.skip('ahkab clone not beside the interface')
            result = ns.draw(parse(path))
            assert 'svg' in result, (name, result)
            hard, _soft = sc._collisions(last['cv'])
            assert hard == 0, (name, hard)
    finally:
        sc._Canvas.flush = orig


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
