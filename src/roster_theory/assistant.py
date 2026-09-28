"""Compatibility import for the Draft advice module."""

import sys

from roster_theory.draft import assistant as _assistant


# Preserve public and historically imported private names on one module object.
sys.modules[__name__] = _assistant
