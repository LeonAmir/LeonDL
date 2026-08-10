from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from core.later_store import LaterStore


def main() -> int:
    with TemporaryDirectory(prefix="leon-later-smoke-") as temp_dir:
        store = LaterStore(Path(temp_dir))
        added = store.add_many([
            {
                "url": "https://example.com/media",
                "title": "Example media",
                "service": "Example",
                "preset": "auto",
                "preset_label": "Automatic",
                "output_dir": "C:/Downloads",
            }
        ])
        assert added == 1
        assert len(store.load()) == 1
        assert store.add_many([
            {
                "url": "https://example.com/media",
                "preset": "auto",
                "output_dir": "C:/Downloads",
            }
        ]) == 0
        assert store.update_matching(
            "https://example.com/media",
            "auto",
            "C:/Downloads",
            {
                "duration": 125,
                "size_bytes": 1234567,
                "size_confidence": "estimated",
                "metadata_status": "ready",
            },
        )
        enriched = store.load()[0]
        assert enriched["duration"] == 125
        assert enriched["size_bytes"] == 1234567
        assert enriched["metadata_status"] == "ready"
        store.remove_indexes([0])
        assert store.load() == []
    print("Download Later store smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
