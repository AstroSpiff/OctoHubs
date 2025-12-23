"""
WSGI entry point per Waitress e altri server di produzione.
Uso: waitress-serve --host=127.0.0.1 --port=5050 wsgi:application
"""
import os
import sys

# Assicurati che il percorso dell'app sia nel sys.path
sys.path.insert(0, os.path.dirname(__file__))

# Importa la funzione che crea l'app
from app import create_dashboard_app

# Crea l'applicazione Flask
application = create_dashboard_app()

# Alias per compatibilità
app = application
