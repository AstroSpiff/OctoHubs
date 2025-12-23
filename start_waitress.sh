#!/bin/bash
# Script per avviare l'app con Waitress (WSGI server)
# SSE funziona perfettamente con questo server

cd "$(dirname "$0")"

# Attiva virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Virtual environment non trovato. Esegui prima: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

echo "Avvio server con Waitress..."
echo "Dashboard disponibile su: http://127.0.0.1:5050"
echo "Configurazione: 16 threads, channel-timeout 300s"
echo "Premi Ctrl+C per fermare"
echo ""

waitress-serve --host=127.0.0.1 --port=5050 --threads=16 --channel-timeout=300 wsgi:application
