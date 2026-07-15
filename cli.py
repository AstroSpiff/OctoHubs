"""
Command-line entrypoint for OctoHub.
"""

import argparse
import sys

from core.config_manager import load_config
from services.health import validate_connections
from services.requests_processor import process_requests


def _print_fastapi_start_hint(port: int = 8000) -> None:
    """Print the recommended FastAPI startup command."""
    print("Avvia l'app FastAPI con:")
    print(f"  uvicorn asgi:app --reload --host 0.0.0.0 --port {port}")


def parse_args():
    parser = argparse.ArgumentParser(description="OctoHub")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Avvia l'interfaccia web per risultati e regole di ricerca",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Forza l'apertura della pagina di configurazione",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Esegue immediatamente lo scan da linea di comando",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.configure:
        print("Configurazione iniziale disponibile su /setup.")
        _print_fastapi_start_hint()
        sys.exit(0)

    config, is_valid = load_config()

    if not config or not is_valid:
        print("Configurazione mancante o non valida.")
        _print_fastapi_start_hint()
        sys.exit(0)

    if args.web:
        _print_fastapi_start_hint()
    elif args.cli:
        if not validate_connections(config):
            sys.exit(1)
        summary = process_requests(config)
        print(f"\nRisultati salvati. Trovati contenuti per {summary.get('found', 0)} richieste.")
    else:
        _print_fastapi_start_hint()


if __name__ == "__main__":
    main()
