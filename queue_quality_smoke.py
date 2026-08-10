from __future__ import annotations

import tempfile
from pathlib import Path

from core.later_store import LaterStore


def test_update_index_changes_only_target_row() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = LaterStore(Path(temp_dir))
        added = store.add_many([
            {
                "url": "https://www.youtube.com/watch?v=one",
                "preset": "video_720",
                "preset_label": "Video up to 720p",
                "output_dir": "A",
                "size_bytes": 100,
                "metadata_status": "ready",
            },
            {
                "url": "https://www.youtube.com/watch?v=two",
                "preset": "video_720",
                "preset_label": "Video up to 720p",
                "output_dir": "B",
                "size_bytes": 200,
                "metadata_status": "ready",
            },
        ])
        assert added == 2
        before = store.load()
        assert len(before) == 2

        assert store.update_index(0, {
            "preset": "video_1080",
            "preset_label": "Video up to 1080p",
            "size_bytes": None,
            "metadata_status": "recalculating",
        })
        after = store.load()
        assert after[0]["preset"] == "video_1080"
        assert after[0]["size_bytes"] is None
        assert after[0]["metadata_status"] == "recalculating"
        assert after[1] == before[1]


def test_queue_ui_wiring() -> None:
    source = Path("ui/window.py").read_text(encoding="utf-8")
    assert 'quality_combo.setObjectName("queuePresetCombo")' in source
    assert 'self.later_table.setCellWidget(row, 5, quality_combo)' in source
    assert 'self._later_preset_changed(source_row' in source
    assert 'estimate_selected_media_size(' in source
    assert '"metadata_status": "recalculating"' in source
    assert 'self._later_metadata_cache[url] = dict(info)' in source
    assert 'self._start_later_metadata_fetch([entry])' in source


def test_version_contract() -> None:
    assert Path("VERSION").read_text(encoding="utf-8").strip() == "2.6.2"
    manifest = Path("chrome_extension/manifest.json").read_text(encoding="utf-8")
    assert '"version": "2.6.2"' in manifest


if __name__ == "__main__":
    test_update_index_changes_only_target_row()
    test_queue_ui_wiring()
    test_version_contract()
    print("queue quality smoke: ok")
