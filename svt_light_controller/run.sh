#!/usr/bin/with-contenv bash
set -euo pipefail

python3 /ui_server.py &
python3 /svtlc.py