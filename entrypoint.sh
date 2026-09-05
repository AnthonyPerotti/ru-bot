#!/bin/sh
set -e

# Se a pasta /app/data existe e ainda nao tem config.json, inicializa a partir do padrao
if [ -d "/app/data" ] && [ ! -f "/app/data/config.json" ]; then
    if [ -f "/app/config.json" ]; then
        cp /app/config.json /app/data/config.json
    fi
fi

# Run local web server in background
python server.py &

# Run scheduler daemon in foreground
exec python scheduler.py
