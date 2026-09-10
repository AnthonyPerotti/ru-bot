#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "=== RU Bot UFSM ==="
echo "Instalando dependencias..."
pip install -r requirements.txt
playwright install chromium

echo "Iniciando servidor web em http://localhost:3456..."
python server.py &
SERVER_PID=$!

echo "Iniciando agendador..."
python scheduler.py &
SCHED_PID=$!

trap "kill $SERVER_PID $SCHED_PID" EXIT
wait
