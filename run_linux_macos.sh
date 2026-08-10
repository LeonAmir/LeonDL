#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

install_python() {
  if command -v brew >/dev/null 2>&1; then
    brew install python@3.12
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm python python-pip
  else
    echo "Python 3.10 or newer is required and could not be installed automatically."
    exit 2
  fi
}

if ! command -v python3 >/dev/null 2>&1; then
  install_python
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'; then
  install_python
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip setuptools wheel --disable-pip-version-check
.venv/bin/python bootstrap.py --strict
LEON_BOOTSTRAP_DONE=1 .venv/bin/python app.py
