"""Backward-compat alias: real implementation lives in digest/collector.py.

`import work_digest` returns the collector module itself, so attribute
patches (e.g. monkeypatch in tests) apply to the running code.
`python work_digest.py` still works as the digest CLI via systemd.
"""

import sys as _sys

from digest import collector as _collector

_sys.modules[__name__] = _collector

if __name__ == "__main__":
    raise SystemExit(_collector.main())
