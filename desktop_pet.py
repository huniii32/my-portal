"""Backward-compat alias: real implementation lives in gombi/desktop_pet.py.

`import desktop_pet` returns the gombi module itself, so the GTK pet,
its helpers, and `python desktop_pet.py` (systemd) keep working.
"""

import sys as _sys

from gombi import desktop_pet as _pet

_sys.modules[__name__] = _pet

if __name__ == "__main__":
    _pet.main()
