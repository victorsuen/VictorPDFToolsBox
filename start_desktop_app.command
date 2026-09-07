#!/bin/sh
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  exec python3 qt_app.py
fi
exec python qt_app.py
