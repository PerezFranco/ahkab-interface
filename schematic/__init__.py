# Symbulator's schematic generator, forked for "An interface for ahkab".
#
# Copyright 2026 Roberto Perez-Franco
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Only the four modules the drawing needs are here: schematic, elements,
# messages and si_prefix. Symbulator's solver is not. elements._numeric()
# reaches for it when checking mutual inductances; it catches the failure
# and skips those numeric checks, which the drawing does not rely on.
