#!/bin/sh
set -e

# Run local web server in background
python server.py &

# Run scheduler daemon in foreground
exec python scheduler.py
