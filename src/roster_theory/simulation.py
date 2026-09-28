"""Compatibility import for the Draft simulation module."""

import sys

from roster_theory.draft import simulation as _simulation


# Keep public and historically imported private names on one module object.
sys.modules[__name__] = _simulation
