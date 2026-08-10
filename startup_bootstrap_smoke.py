from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

launcher = (ROOT / "launcher.pyw").read_text(encoding="utf-8")
app = (ROOT / "app.py").read_text(encoding="utf-8")
setup = (ROOT / "setup_windows.bat").read_text(encoding="utf-8")
bootstrap = (ROOT / "bootstrap.py").read_text(encoding="utf-8")

assert 'bootstrap.py", "--skip-external", "--quiet"' in launcher
assert "def _select_runtime_dir()" in launcher
assert 'glob("LeonDL-v*")' in launcher
assert 'bootstrap.py", "--strict", "--quiet"' not in launcher
assert "include_external=False" in app
assert "bootstrap.py --skip-external" in setup
assert "pip install --upgrade pip setuptools wheel" not in setup
assert '"--timeout"' in bootstrap and '"45"' in bootstrap
assert '"--retries"' in bootstrap and '"2"' in bootstrap

print("Startup bootstrap smoke test passed.")
