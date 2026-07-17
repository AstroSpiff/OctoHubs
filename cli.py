"""
Command-line entrypoint for OctoHub.
"""

import argparse
import json
import os
import sys


def _print_fastapi_start_hint(port: int = 8000) -> None:
    """Print the recommended FastAPI startup command."""
    print("Avvia l'app FastAPI con:")
    print(f"  uvicorn asgi:app --reload --host 0.0.0.0 --port {port}")


def parse_args(argv=None):
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
    subparsers = parser.add_subparsers(dest="command")

    db_parser = subparsers.add_parser(
        "db",
        help="Gestisce stato e migrazioni database",
    )
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    db_subparsers.add_parser("status", help="Mostra lo stato migrazioni database")
    db_subparsers.add_parser("validate", help="Valida il registro migrazioni database")
    upgrade_parser = db_subparsers.add_parser("upgrade", help="Applica migrazioni database pendenti")
    upgrade_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra le migrazioni pendenti senza modificare il database",
    )

    return parser.parse_args(argv)


def _load_database_settings_for_cli() -> dict:
    from core.config import CONFIG_FILE, _merge_database_settings
    from core.storage import StorageError
    from services.manager import _apply_db_env_overrides

    file_config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as handle:
                file_config = json.load(handle)
        except (json.JSONDecodeError, IOError) as exc:
            raise StorageError(f"Configurazione non leggibile: {exc}") from exc

    db_settings = _merge_database_settings(file_config.get("DATABASE"))
    db_settings["PASSWORD"] = ""
    db_settings["URL"] = ""
    db_settings = _apply_db_env_overrides(db_settings)
    if not db_settings.get("ENABLED"):
        raise StorageError("Database non abilitato nella configurazione")
    return db_settings


def _format_list(values) -> str:
    return ", ".join(values) if values else "-"


def _handle_db_command(args) -> int:
    from core.storage import DatabaseStorage, StorageError

    try:
        backend = DatabaseStorage(_load_database_settings_for_cli())
        if args.db_command == "status":
            status = backend.get_migration_status()
            print("Database migrations")
            print(f"Registry: {'presente' if status.registry_exists else 'mancante'}")
            print(f"Disponibili: {_format_list(status.available)}")
            print(f"Applicate: {_format_list(status.applied)}")
            print(f"Pendenti: {_format_list(status.pending)}")
            if status.unknown_applied:
                print(f"Sconosciute: {_format_list(status.unknown_applied)}")
            return 0

        if args.db_command == "validate":
            result = backend.validate_migrations()
            print("OK" if result["ok"] else "ERROR")
            for error in result["errors"]:
                print(f"- {error}")
            return 0 if result["ok"] else 1

        if args.db_command == "upgrade":
            result = backend.apply_migrations(dry_run=args.dry_run)
            if args.dry_run:
                print("Dry-run migrazioni database")
                print(f"Pendenti: {_format_list(result['pending'])}")
            else:
                print("Migrazioni database applicate")
                backup = result.get("backup")
                if backup:
                    print(f"Backup: {backup.get('path')}")
                    print(f"Manifest: {backup.get('manifest_path')}")
                print(f"Applicate ora: {_format_list(result['applied'])}")
                print(f"Pendenti iniziali: {_format_list(result['pending'])}")
            return 0
    except StorageError as exc:
        print(f"Errore database: {exc}")
        return 1

    print(f"Comando database non riconosciuto: {args.db_command}")
    return 1


def main() -> None:
    args = parse_args()

    if getattr(args, "command", None) == "db":
        sys.exit(_handle_db_command(args))

    from core.config_manager import load_config
    from services.health import validate_connections
    from services.requests_processor import process_requests

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
