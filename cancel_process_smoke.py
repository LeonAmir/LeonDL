from __future__ import annotations

import sys
import threading
import time

from core.optional_engines import OptionalEngineError, _run_process


def main() -> None:
    cancel = threading.Event()
    timer = threading.Timer(0.25, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        _run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            lambda _message: None,
            cancel,
        )
    except OptionalEngineError as exc:
        assert "cancel" in str(exc).lower()
    else:
        raise AssertionError("silent child process was not cancelled")
    finally:
        timer.cancel()
    elapsed = time.monotonic() - started
    assert elapsed < 4.0, elapsed
    print(f"Optional-engine cancellation smoke test: OK ({elapsed:.2f}s)")


if __name__ == "__main__":
    main()
