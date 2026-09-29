#!/bin/bash
set -e
PORT="${PORT:-8788}"
mkdir -p /config/public
python3 /config/render.py   # first bake, fails loudly if anything's broken
( cd /config/public && python3 -m http.server "$PORT" ) &
while true; do
  sleep 60
  python3 /config/render.py || echo "render failed at $(date)"
done
