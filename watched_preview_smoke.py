from __future__ import annotations

import ast
from pathlib import Path


def main() -> int:
    source = (Path(__file__).resolve().parent / "ui" / "window.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    helper = methods.get("_apply_mark_watched_to_main_preview")
    preview = methods.get("_preview_all_urls")
    assert helper is not None, "Main-preview watched helper is missing"
    assert preview is not None, "Main preview method is missing"
    helper_source = ast.get_source_segment(source, helper) or ""
    preview_source = ast.get_source_segment(source, preview) or ""
    assert 'auth_options["mark_watched"] = True' in helper_source
    assert "manual_cookie_text.strip()" in helper_source
    assert "cookiesfrombrowser" in helper_source and "cookiefile" in helper_source
    assert "_apply_mark_watched_to_main_preview" in preview_source
    assert "PreviewWorker" in preview_source
    print("Watched preview smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
