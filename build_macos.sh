#!/bin/sh
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt pyinstaller
python3 build_desktop.py --zip
echo
echo "Mac app and zip are in ./dist"
