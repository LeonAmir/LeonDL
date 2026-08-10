from __future__ import annotations

import sys

from core.browser_bridge import run_native_host


if __name__ == "__main__":
    raise SystemExit(run_native_host(sys.argv))
