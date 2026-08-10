from __future__ import annotations

import tempfile
from pathlib import Path

from core.history_store import HistoryStore


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        store = HistoryStore(Path(temporary), max_items=50)
        store.add_many([
            {
                "url": "https://example.test/video",
                "title": "Example",
                "service": "Example",
                "output_dir": temporary,
                "preset": "auto",
            }
        ])
        items = store.load()
        assert len(items) == 1
        assert items[0]["title"] == "Example"
        store.clear()
        assert store.load() == []
    print("History storage smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
