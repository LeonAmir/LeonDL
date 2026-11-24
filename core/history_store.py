from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class HistoryStore:
    """Small JSON-backed download history.

    The file lives beside the existing Leon settings. Writes are atomic so an
    interrupted application close cannot leave a half-written history file.
    """

    def __init__(self, config_dir: Path, *, max_items: int = 1000) -> None:
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / "history.json"
        self.usage_path = self.config_dir / "download_usage.json"
        self.max_items = max(50, int(max_items))

    def load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return []
        if not isinstance(raw, list):
            return []
        items: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not url and not title:
                continue
            items.append(dict(entry))
        return items[: self.max_items]

    def add_many(self, entries: Iterable[dict[str, Any]]) -> None:
        existing = self.load()
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        new_items: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for raw in entries:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item.setdefault("downloaded_at", now)
            item.setdefault("status", "completed")
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            output = str(item.get("output_dir") or "").strip()
            if not url and not title:
                continue
            key = (url, title, output)
            if key in seen:
                continue
            seen.add(key)
            new_items.append(item)
        if not new_items:
            return
        self._write((new_items + existing)[: self.max_items])

    def clear(self) -> None:
        self._write([])

    def remove_indexes(self, indexes: Iterable[int]) -> None:
        items = self.load()
        remove = {int(index) for index in indexes if int(index) >= 0}
        self._write([item for index, item in enumerate(items) if index not in remove])

    def received_bytes(self) -> int:
        try:
            return max(0, int(json.loads(self.usage_path.read_text(encoding="utf-8"))["received_bytes"]))
        except (OSError, ValueError, TypeError, KeyError):
            return 0

    def add_received_bytes(self, amount: int) -> None:
        if amount > 0:
            self._write_json(self.usage_path, {"received_bytes": self.received_bytes() + amount})

    def _write(self, items: list[dict[str, Any]]) -> None:
        self._write_json(self.path, items)

    def _write_json(self, path: Path, value: Any) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix="history-", suffix=".tmp", dir=str(self.config_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
