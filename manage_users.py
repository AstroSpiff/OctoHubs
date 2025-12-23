#!/usr/bin/env python3
"""CLI helper to manage OctoHub users."""
import argparse
import os
from typing import Optional

from flask import Flask

from auth import (
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


def _bootstrap_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "octohub"
    init_auth(app)
    return app


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
    if user.is_active == active:
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
                "yes" if user.is_admin else "no",
                "yes" if user.is_active else "no",
                user.get_role() if hasattr(user, "get_role") else "-",
                user.email or "-",
            )
        )


def main():
    parser = argparse.ArgumentParser(description="OctoHub user management")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Elenca tutti gli utenti")

    create = sub.add_parser("create", help="Crea un nuovo utente")
    create.add_argument("--username", required=True)
    create.add_argument("--password", required=True)
    create.add_argument("--email", default=None)
    create.add_argument("--role", choices=["admin", "user", "viewer"], default=None)
    create.add_argument("--admin", action="store_true")

    delete = sub.add_parser("delete", help="Elimina un utente")
    delete.add_argument("--username", required=True)

    passwd = sub.add_parser("set-password", help="Aggiorna password utente")
    passwd.add_argument("--username", required=True)
    passwd.add_argument("--password", required=True)

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

    args = parser.parse_args()

    app = _bootstrap_app()
    with app.app_context():
        if args.command == "list":
            _print_users()
        elif args.command == "create":
            create_user(args.username, args.password, args.email, args.admin, args.role)
        elif args.command == "delete":
            user = get_user_by_username(args.username)
            if not user:
                print(f"[AUTH] Utente non trovato: {args.username}")
            else:
                delete_user(user)
        elif args.command == "set-password":
            user = get_user_by_username(args.username)
            if not user:
                print(f"[AUTH] Utente non trovato: {args.username}")
            else:
                update_user_password(user, args.password)
        elif args.command == "disable":
            _set_active(args.username, False)
        elif args.command == "enable":
            _set_active(args.username, True)
        elif args.command == "make-admin":
            _set_admin(args.username, True)
        elif args.command == "remove-admin":
            _set_admin(args.username, False)
        elif args.command == "set-role":
            user = get_user_by_username(args.username)
            if not user:
                print(f"[AUTH] Utente non trovato: {args.username}")
            else:
                set_user_role(user, args.role)
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


if __name__ == "__main__":
    main()
