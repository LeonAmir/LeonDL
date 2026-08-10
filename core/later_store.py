from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class LaterStore:
    """Persistent download-later queue stored as JSON.

    Entries are intentionally lightweight and contain the URL plus a snapshot
    of the relevant output settings. Writes are atomic to avoid corruption if
    Windows closes the application while the queue is being updated.
    """

    def __init__(self, config_dir: Path, *, max_items: int = 2000) -> None:
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / "download_later.json"
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
            if not url:
                continue
            items.append(dict(entry))
        return items[: self.max_items]

    def add_many(self, entries: Iterable[dict[str, Any]]) -> int:
        existing = self.load()
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        existing_keys = {
            (
                str(item.get("url") or "").strip(),
                str(item.get("preset") or "").strip(),
                str(item.get("output_dir") or "").strip(),
            )
            for item in existing
        }
        new_items: list[dict[str, Any]] = []
        for raw in entries:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            item["url"] = url
            item.setdefault("title", url)
            item.setdefault("service", "")
            item.setdefault("added_at", now)
            item.setdefault("status", "waiting")
            key = (
                url,
                str(item.get("preset") or "").strip(),
                str(item.get("output_dir") or "").strip(),
            )
            if key in existing_keys:
                continue
            existing_keys.add(key)
            new_items.append(item)
        if not new_items:
            return 0
        self._write((new_items + existing)[: self.max_items])
        return len(new_items)

    def update_matching(
        self,
        url: str,
        preset: str,
        output_dir: str,
        updates: dict[str, Any],
    ) -> bool:
        """Merge metadata into the matching persistent queue entry.

        The same URL can exist more than once when the output preset or output
        directory differs, so all three values form the stable queue key.
        """
        target = (
            str(url or "").strip(),
            str(preset or "").strip(),
            str(output_dir or "").strip(),
        )
        if not target[0]:
            return False
        items = self.load()
        changed = False
        for item in items:
            key = (
                str(item.get("url") or "").strip(),
                str(item.get("preset") or "").strip(),
                str(item.get("output_dir") or "").strip(),
            )
            if key != target:
                continue
            for name, value in dict(updates or {}).items():
                if item.get(name) != value:
                    item[name] = value
                    changed = True
            break
        if changed:
            self._write(items)
        return changed

    def update_index(self, index: int, updates: dict[str, Any]) -> bool:
        """Merge updates into one queue row addressed by its persisted index.

        This is intentionally separate from ``update_matching`` because the
        preset is part of the normal stable key. Editing a Queue row's preset
        therefore changes the key itself and must target the exact row.
        """
        try:
            target_index = int(index)
        except (TypeError, ValueError):
            return False
        items = self.load()
        if target_index < 0 or target_index >= len(items):
            return False
        item = items[target_index]
        changed = False
        for name, value in dict(updates or {}).items():
            if item.get(name) != value:
                item[name] = value
                changed = True
        if changed:
            self._write(items)
        return changed

    def remove_indexes(self, indexes: Iterable[int]) -> None:
        items = self.load()
        remove = {int(index) for index in indexes if int(index) >= 0}
        self._write([item for index, item in enumerate(items) if index not in remove])

    def clear(self) -> None:
        self._write([])

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(items, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix="download-later-", suffix=".tmp", dir=str(self.config_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
