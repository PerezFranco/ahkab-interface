# An interface for ahkab -- drawing an ahkab circuit with the forked
# Symbulator schematic generator.
#
# Copyright 2026 Roberto Perez-Franco
# SPDX-License-Identifier: GPL-2.0-or-later
"""Translate a parsed ahkab circuit into a Symbulator circuit description,
and draw it.

The circuit comes from ahkab's own netlist parser, so the drawing shows
exactly what was simulated, subcircuits already expanded. Each element is
renamed to the Symbulator kind letter, a double underscore and its ahkab
name (``v1`` becomes ``e__v1``); the forked generator shows such names by
the ahkab name alone, so the drawing's labels match the netlist and the
result tables.

Conventions were checked by solving the same circuits in both programs:
the first node of a voltage source is its + terminal, a current source
drives current from its first node through itself to its second, and the
current through a voltage source is taken the same way round, so
dependent sources translate without any change of sign.

The nonlinear devices go to the fork's own kinds: a diode is ``d``
(anode, cathode), a MOSFET ``n`` or ``p`` by its model's channel type
(drain, gate, source, bulk -- ahkab's order, read off ``n1``, ``ng``,
``n2``, ``nb``), a switch ``w`` (its two output nodes, then its two
sensing nodes, then what it senses written the way a dependent source's
control is, so the drawing marks the sensed element). A diode is
labelled by its model, a MOSFET by its model and W/L.
"""

import math
import re

# ahkab component class -> Symbulator kind letter.
KINDS = {
    'Resistor': 'r', 'Capacitor': 'c', 'Inductor': 'l',
    'VSource': 'e', 'ISource': 'j',
    'EVSource': 'e', 'HVSource': 'e',     # voltage-controlled, current-controlled
    'GISource': 'j', 'FISource': 'j',
    'InductorCoupling': 'm',
    'diode': 'd', 'switch_device': 'w',
    # a MOSFET is 'n' or 'p' by its model; see kind_of
}
MOS_CLASSES = ('mosq_device', 'ekv_device')


def kind_of(el):
    """The Symbulator kind letter for an ahkab element, or None."""
    cls = type(el).__name__
    if cls in MOS_CLASSES:
        model = el.mosq_model if cls == 'mosq_device' else el.ekv_model
        return 'n' if model.NPMOS == 1 else 'p'
    return KINDS.get(cls)


# Readable names for what the drawing cannot show. Empty now that the
# diode, the MOSFET and the switch draw; kept so an element class this
# translator has never met is still reported by name rather than drawn
# wrong.
UNSUPPORTED_NAMES = {}

_PREFIXES = [(1e9, 'G'), (1e6, 'M'), (1e3, 'k'), (1.0, ''), (1e-3, 'm'),
             (1e-6, 'u'), (1e-9, 'n'), (1e-12, 'p'), (1e-15, 'f')]


def si(x):
    """``1500.0`` -> ``'1.5k'``, ``1.5e-05`` -> ``'15u'``: the shorthand a
    netlist would use. The generator shows ``u`` as micro.

    A value from 0.1 up to 1 stays a plain decimal -- ``0.51`` rather
    than ``510m`` -- as the netlist writes it; the generator letters
    the drawn label the same way (``_engineering`` in schematic.py)."""
    x = float(x)
    if x == 0 or not math.isfinite(x):
        return '0' if x == 0 else repr(x)
    if abs(x) >= 1e12:
        return '%g' % x
    if 0.1 <= abs(x) < 1:
        return '%g' % float('%.6g' % x)
    for scale, prefix in _PREFIXES:
        if abs(x) >= scale * (1 - 1e-9):
            return '%g%s' % (float('%.6g' % (x / scale)), prefix)
    return '%g' % x


def gain(x):
    return '%g' % float('%.6g' % float(x))


class Translation(object):
    """The Symbulator description of an ahkab circuit, or why there is none."""

    def __init__(self, circ):
        self.circ = circ
        self.lines = []
        self.unsupported = []      # (part_id, readable kind)
        self.names = {}            # ahkab part_id (lower) -> Symbulator name
        self._nodes = {}
        self._used_nodes = set()
        self._used_names = set()
        self._translate()

    @property
    def description(self):
        return ':'.join(self.lines) if self.lines and not self.unsupported else None

    # -- names ----------------------------------------------------------------

    def node(self, n):
        if n == 0 or n == self.circ.gnd:     # ahkab's internal index for ground is 0
            return '0'
        if n not in self._nodes:
            raw = str(self.circ.nodes_dict[n])
            clean = re.sub(r'[^A-Za-z0-9]', '', raw) or 'n%d' % n
            if clean == '0' or clean.lower() in self._used_nodes:
                clean = 'n%d' % n
            self._used_nodes.add(clean.lower())
            self._nodes[n] = clean
        return self._nodes[n]

    def name(self, kind, part_id):
        key = part_id.lower()
        if key not in self.names:
            clean = re.sub(r'[^A-Za-z0-9]', '', part_id) or kind
            if not clean[0].isalpha():
                clean = kind + clean
            candidate, i = '%s__%s' % (kind, clean), 2
            while candidate.lower() in self._used_names:
                candidate, i = '%s__%s%d' % (kind, clean, i), i + 1
            self._used_names.add(candidate.lower())
            self.names[key] = candidate
        return self.names[key]

    # -- elements -------------------------------------------------------------

    def _translate(self):
        elements = list(self.circ)
        # Name every translatable element first, so a controlled source can
        # refer to one that appears later in the netlist.
        for el in elements:
            kind = kind_of(el)
            if kind:
                self.name(kind, el.part_id)
        for el in elements:
            cls = type(el).__name__
            kind = kind_of(el)
            if kind is None:
                self.unsupported.append((el.part_id, UNSUPPORTED_NAMES.get(cls, cls)))
                continue
            me = self.names[el.part_id.lower()]
            if kind == 'm':
                l1 = self.names.get(str(el.L1).lower())
                l2 = self.names.get(str(el.L2).lower())
                if not (l1 and l2):
                    self.unsupported.append((el.part_id, 'coupling to a missing inductor'))
                    continue
                self.lines.append('%s,%s,%s,k=%s' % (me, l1, l2, gain(el.K)))
                continue
            if kind in ('n', 'p'):
                # ahkab's mosq_device and ekv_device: n1 is the drain, ng
                # the gate, n2 the source, nb the bulk (mosq.py, ekv.py).
                self.lines.append('%s,%s,%s,%s,%s,%s' % (
                    me, self.node(el.n1), self.node(el.ng), self.node(el.n2),
                    self.node(el.nb), self._mos_label(el)))
                continue
            if kind == 'w':
                # switch_device: n1, n2 conduct; sn1, sn2 sense (switch.py)
                self.lines.append('%s,%s,%s,%s,%s,%s' % (
                    me, self.node(el.n1), self.node(el.n2), self.node(el.sn1),
                    self.node(el.sn2), self._voltage(el.sn1, el.sn2, el)))
                continue
            value = self._value(el, cls)
            self.lines.append('%s,%s,%s,%s' % (me, self.node(el.n1), self.node(el.n2), value))

    def _mos_label(self, el):
        """``nch 1µ/1µ``: the model's name and the device's W/L, the way
        an analogue schematic annotates a transistor."""
        model = el.mosq_model if type(el).__name__ == 'mosq_device' else el.ekv_model
        w, l = si(el.device.W), si(el.device.L)
        return '%s %s/%s' % (_label(model.name), w.replace('u', 'µ'), l.replace('u', 'µ'))

    def _value(self, el, cls):
        if cls == 'diode':
            return _label(el.model.name)
        if cls in ('Resistor', 'Capacitor', 'Inductor'):
            return si(el.value)
        if cls in ('VSource', 'ISource'):
            if getattr(el, 'is_timedependent', False) and getattr(el, '_time_function', None) is not None:
                return type(el._time_function).__name__.lower()
            if el.abs_ac and not el.dc_value:
                return 'AC %s' % si(el.abs_ac)
            return si(el.dc_value)
        if cls in ('EVSource', 'GISource'):
            return '%s*%s' % (gain(el.alpha), self._voltage(el.sn1, el.sn2, el))
        if cls in ('HVSource', 'FISource'):
            sense = self.names.get(str(el.source_id).lower())
            return '%s*i%s' % (gain(el.alpha), sense or str(el.source_id))
        raise ValueError(cls)

    def _voltage(self, a, b, source):
        """The voltage from node ``a`` to node ``b``, preferably as the drop
        across an element connected exactly there, so the drawing marks the
        control on that element."""
        for el in self.circ:
            if el is not source and kind_of(el) in ('r', 'c', 'l', 'e', 'j', 'd', 'w'):
                me = self.names[el.part_id.lower()]
                if (el.n1, el.n2) == (a, b):
                    return 'v%s' % me
                if (el.n1, el.n2) == (b, a):
                    return '(-v%s)' % me
        if self.node(b) == '0':
            return 'v%s' % self.node(a)
        if self.node(a) == '0':
            return '(-v%s)' % self.node(b)
        return '(v%s-v%s)' % (self.node(a), self.node(b))


def _label(text):
    """A model name as a label term: the description's separators and
    the generator's own notation (brackets, quotes) taken out."""
    return re.sub(r"[,:\[\]'\s]+", ' ', str(text)).strip() or 'model'


def draw(circ):
    """``{'svg': str}`` or ``{'unsupported': [...]}`` or ``{'error': str}``."""
    t = Translation(circ)
    if t.unsupported:
        kinds = sorted({k for _, k in t.unsupported})
        return {'unsupported': [{'part': p, 'kind': k} for p, k in t.unsupported],
                'message': 'The drawing cannot show %s yet.' % _join(kinds)}
    if not t.lines:
        return {'error': 'The circuit has no elements to draw.'}
    from schematic import schematic as sc
    try:
        return {'svg': sc.to_svg(t.description), 'description': t.description}
    except Exception as e:  # the generator refuses some topologies; say so
        return {'error': 'The drawing could not be made: %s' % e, 'description': t.description}


_PLURAL = {'diode': 'diodes', 'MOSFET': 'MOSFETs', 'switch': 'switches'}


def _join(words):
    words = [_PLURAL.get(w, w) for w in words]
    return words[0] if len(words) == 1 else ', '.join(words[:-1]) + ' or ' + words[-1]
