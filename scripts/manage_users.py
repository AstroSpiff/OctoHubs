#!/usr/bin/env python3
"""CLI helper to manage OctoHubs users."""
import argparse
import getpass
import sys
from pathlib import Path

# Direct execution (the documented container command) places ``scripts/`` on
# sys.path. Add the repository root explicitly so it has the same imports as
# ``python -m scripts.manage_users`` without relying on PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.password_policy import PasswordTooLongError, bcrypt_password_bytes  # noqa: E402

from core.auth import (  # noqa: E402
    init_auth,
    get_user_by_username,
    create_user,
    update_user_password,
    delete_user,
    get_all_users,
    toggle_user_active,
    set_user_role,
    get_audit_logs,
)


def _bootstrap_app() -> bool:
    """Initialize authentication system without Flask."""
    return bool(init_auth(create_default_admin=False))


def _password_argument(value: str) -> str:
    try:
        bcrypt_password_bytes(value)
    except PasswordTooLongError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value


def _add_password_input(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--password-file", help="Legge la password da un file protetto")
    source.add_argument("--password-stdin", action="store_true", help="Legge la password da stdin")


def _resolve_password(args: argparse.Namespace) -> str:
    if args.password_file:
        lines = Path(args.password_file).read_text(encoding="utf-8").splitlines()
        if not lines:
            raise argparse.ArgumentTypeError("Il file password è vuoto")
        value = lines[0]
    elif args.password_stdin:
        value = sys.stdin.readline().rstrip("\r\n")
    else:
        value = getpass.getpass("Password: ")
    return _password_argument(value)


def _set_admin(username: str, is_admin: bool) -> bool:
    role = "admin" if is_admin else "user"
    user = get_user_by_username(username)
    if not user:
        print(f"[AUTH] Utente non trovato: {username}")
        return False
    return set_user_role(user, role)


def _set_active(username: str, active: bool) -> bool:
    user = get_user_by_username(username)
    if not user:
        print(f"[AUTH] Utente non trovato: {username}")
        return False
    if bool(user.is_active) == active:
        status = "attivo" if active else "disabilitato"
        print(f"[AUTH] Utente {username} gia {status}")
        return True
    return toggle_user_active(user)


def _print_users():
    users = get_all_users()
    if not users:
        print("[AUTH] Nessun utente trovato")
        return
    print("{:<20} {:<6} {:<9} {:<10} {:<25}".format("Username", "Admin", "Attivo", "Ruolo", "Email"))
    print("-" * 76)
    for user in users:
        print(
            "{:<20} {:<6} {:<9} {:<10} {:<25}".format(
                user.username,
                "yes" if bool(user.is_admin) else "no",
                "yes" if bool(user.is_active) else "no",
                user.get_role() if hasattr(user, "get_role") else "-",
                user.email or "-",
            )
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OctoHubs user management")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Elenca tutti gli utenti")

    create = sub.add_parser("create", help="Crea un nuovo utente")
    create.add_argument("--username", required=True)
    _add_password_input(create)
    create.add_argument("--email", default=None)
    create.add_argument("--role", choices=["admin", "user", "viewer"], default=None)
    create.add_argument("--admin", action="store_true")

    delete = sub.add_parser("delete", help="Elimina un utente")
    delete.add_argument("--username", required=True)

    passwd = sub.add_parser("set-password", help="Aggiorna password utente")
    passwd.add_argument("--username", required=True)
    _add_password_input(passwd)

    disable = sub.add_parser("disable", help="Disabilita un utente")
    disable.add_argument("--username", required=True)

    enable = sub.add_parser("enable", help="Riabilita un utente")
    enable.add_argument("--username", required=True)

    make_admin = sub.add_parser("make-admin", help="Promuove un utente ad admin")
    make_admin.add_argument("--username", required=True)

    remove_admin = sub.add_parser("remove-admin", help="Rimuove privilegi admin")
    remove_admin.add_argument("--username", required=True)

    set_role = sub.add_parser("set-role", help="Imposta il ruolo di un utente")
    set_role.add_argument("--username", required=True)
    set_role.add_argument("--role", required=True, choices=["admin", "user", "viewer"])

    audit = sub.add_parser("audit", help="Mostra audit log")
    audit.add_argument("--limit", type=int, default=50)

    args = parser.parse_args(argv)

    try:
        if not _bootstrap_app():
            print("[AUTH] Inizializzazione database non riuscita", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"[AUTH] Inizializzazione database non riuscita: {exc}", file=sys.stderr)
        return 1

    if args.command == "list":
        _print_users()
        return 0
    elif args.command == "create":
        return 0 if create_user(args.username, _resolve_password(args), args.email, args.admin, args.role) else 1
    elif args.command == "delete":
        user = get_user_by_username(args.username)
        if not user:
            print(f"[AUTH] Utente non trovato: {args.username}")
            return 1
        return 0 if delete_user(user) else 1
    elif args.command == "set-password":
        user = get_user_by_username(args.username)
        if not user:
            print(f"[AUTH] Utente non trovato: {args.username}")
            return 1
        return 0 if update_user_password(user, _resolve_password(args)) else 1
    elif args.command == "disable":
        return 0 if _set_active(args.username, False) else 1
    elif args.command == "enable":
        return 0 if _set_active(args.username, True) else 1
    elif args.command == "make-admin":
        return 0 if _set_admin(args.username, True) else 1
    elif args.command == "remove-admin":
        return 0 if _set_admin(args.username, False) else 1
    elif args.command == "set-role":
        user = get_user_by_username(args.username)
        if not user:
            print(f"[AUTH] Utente non trovato: {args.username}")
            return 1
        return 0 if set_user_role(user, args.role) else 1
    elif args.command == "audit":
        logs = get_audit_logs(args.limit)
        if not logs:
            print("[AUTH] Nessun audit log trovato")
        else:
            print("{:<20} {:<12} {:<20} {:<30}".format("Timestamp", "Utente", "Azione", "IP"))
            print("-" * 88)
            for entry in logs:
                timestamp = entry.created_at.strftime("%Y-%m-%d %H:%M:%S")
                print("{:<20} {:<12} {:<20} {:<30}".format(
                    timestamp,
                    entry.username or "-",
                    entry.action,
                    entry.ip_address or "-"
                ))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
