"""
Authentication module with SQLAlchemy.
Manages user accounts, password hashing, and session management.
"""
import json
import logging
import os
import hashlib
import secrets
import bcrypt
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Mapping

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, or_, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.auth_admin_invariant import active_admin_mutation_guard
from core.auth_session_scope import RequestAwareSessionRegistry
from core.client_address import resolve_client_address
from core.database_timeouts import postgres_engine_options
from core.log_sanitization import format_exception_for_log
from core.password_policy import (
    PasswordTooLongError,
    bcrypt_password_bytes,
    is_public_admin_bootstrap_password,
    password_fits_bcrypt,
)
from core.safe_output import safe_print as print
from core.sqlalchemy_session_cleanup import dispose_engine_safely, rollback_session_safely


logger = logging.getLogger(__name__)

# SQLAlchemy setup
Base = declarative_base()

# Database session
db_session = None
_auth_cleanup_pending = None
_auth_cleanup_lock = threading.Lock()

ROLE_VALUES = ("admin", "user", "viewer")
PRIMARY_NAVIGATION_MODES = ("top", "sidebar")
SECONDARY_NAVIGATION_MODES = ("tabs", "sidebar")
DEFAULT_INTERFACE_PREFERENCES = {
    "primary_navigation": "top",
    "secondary_navigation": "tabs",
}
API_TOKEN_SCOPES = (
    "read:status",
    "read:account",
    "read:servers",
    "read:streams",
    "read:users",
    "read:collections",
    "read:libraries",
    "read:research",
    "read:publications",
    "read:configuration",
    "write:configuration",
    "write:account",
    "manage:tokens",
    "admin:accounts",
    "read:event_bridge",
    "write:event_bridge",
    "write:transcode_guard",
    "write:users",
    "write:collections",
    "write:libraries",
    "write:research",
    "write:publications",
    "run:operations",
    "admin:all",
)
API_TOKEN_PERMISSION_PROFILES = {
    "read_only": (
        "read:status",
        "read:account",
        "read:servers",
        "read:streams",
        "read:users",
        "read:collections",
        "read:libraries",
        "read:research",
        "read:publications",
        "read:configuration",
        "read:event_bridge",
    ),
    "operator": (
        "read:status",
        "read:account",
        "read:servers",
        "read:streams",
        "read:users",
        "read:collections",
        "read:libraries",
        "read:research",
        "read:publications",
        "read:configuration",
        "read:event_bridge",
        "write:configuration",
        "write:event_bridge",
        "write:transcode_guard",
        "write:users",
        "write:collections",
        "write:libraries",
        "write:research",
        "write:publications",
        "run:operations",
    ),
    "administrator": ("admin:all",),
}
_UNSET = object()
_API_TOKEN_LAST_USED_INTERVAL = timedelta(minutes=5)
API_TOKEN_MAX_ACTIVE_PER_ACCOUNT = 20
API_TOKEN_MAX_HISTORY_PER_ACCOUNT = 100
API_TOKEN_MAX_LISTED_PER_ACCOUNT = API_TOKEN_MAX_ACTIVE_PER_ACCOUNT + API_TOKEN_MAX_HISTORY_PER_ACCOUNT


def _log_auth_exception(message: str, error: BaseException) -> None:
    """Keep diagnostic context without writing credentials embedded in errors."""
    print(f"[AUTH] {message}:", format_exception_for_log(error), sep="\n")


_API_TOKEN_READ_AUDIT_INTERVAL_SECONDS = 300.0
_AUDIT_RETENTION_DAYS = 90
_audit_state_lock = threading.Lock()
_interface_preferences_write_lock = threading.RLock()
_recent_read_audits: dict[tuple[int, str, str, str], float] = {}
_last_audit_prune_at = 0.0


class AuthStorageError(RuntimeError):
    """Raised when account storage cannot produce an authoritative outcome."""


class AccountUpdateStorageError(AuthStorageError):
    """Raised when an account update fails for an infrastructure reason."""


def _rollback_safely(session: Any) -> None:
    """Best-effort rollback that never masks the primary storage failure."""
    rollback_session_safely(session, context="auth operation")


def _utcnow() -> datetime:
    """Return a naive UTC timestamp for the existing timezone-naive auth schema."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """User model for authentication."""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(120), unique=True, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    role = Column(String(20), default="user", nullable=False)
    auth_epoch = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)

    def set_password(self, password: str):
        """Hash and set the user password."""
        password_bytes = bcrypt_password_bytes(password)
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
        self.password_hash = hashed.decode('utf-8')

    def check_password(self, password: str) -> bool:
        """Verify password against hash."""
        if not password_fits_bcrypt(password):
            return False
        password_bytes = password.encode("utf-8")
        try:
            return bcrypt.checkpw(password_bytes, self.password_hash.encode("utf-8"))
        except (TypeError, ValueError):
            return False

    def update_last_login(self):
        """Update last login timestamp."""
        self.last_login = _utcnow()
        if db_session:
            try:
                db_session.commit()
            except SQLAlchemyError:
                _rollback_safely(db_session)

    def get_role(self) -> str:
        """Return normalized role for the user."""
        is_admin_value = bool(self.is_admin)  # Convert Column to bool
        if is_admin_value:
            return "admin"
        role_value = str(self.role)  # Convert Column to str
        if role_value in ROLE_VALUES:
            return role_value
        return "user"

    def set_role(self, role: str) -> None:
        """Set role and align admin flag."""
        normalized = _normalize_role(role, False)
        self.role = normalized
        self.is_admin = normalized == "admin"

    def __repr__(self):
        return f'<User {self.username}>'


class AuditLog(Base):
    """Audit log for user actions."""
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String(80), nullable=True)
    action = Column(String(120), nullable=False)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
    path = Column(String(255), nullable=True)
    method = Column(String(10), nullable=True)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class UserInterfacePreference(Base):
    """Personal workspace layout preferences kept alongside the login account."""

    __tablename__ = "user_interface_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False, index=True)
    primary_navigation = Column(String(20), default="top", nullable=False)
    secondary_navigation = Column(String(20), default="tabs", nullable=False)
    navigation_order = Column(Text, default="{}", nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)


class ApiToken(Base):
    """Personal API token for external clients such as automation tools or AI agents."""

    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    token_prefix = Column(String(16), nullable=False)
    scopes = Column(Text, default="[]", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)


def _normalize_role(role: Optional[str], is_admin: bool = False) -> str:
    """Normalize role input."""
    if is_admin:
        return "admin"
    if not role:
        return "user"
    role = role.strip().lower()
    if role not in ROLE_VALUES:
        return "user"
    return role


def normalize_api_token_scopes(value: Any) -> list[str]:
    """Return supported API scopes, preserving order and removing duplicates."""
    raw_items: list[Any]
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.replace(",", " ").split()]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    scopes: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        scope = str(item or "").strip().lower()
        if scope not in API_TOKEN_SCOPES or scope in seen:
            continue
        seen.add(scope)
        scopes.append(scope)
    return scopes


def api_token_permission_profile_scopes(profile: Any) -> list[str] | None:
    """Resolve one supported token permission profile to its canonical scopes."""
    profile_id = str(profile or "").strip().lower()
    scopes = API_TOKEN_PERMISSION_PROFILES.get(profile_id)
    return list(scopes) if scopes is not None else None


def api_token_permission_profile_id(scopes: Any) -> str | None:
    """Return the matching profile id only for an exact stored scope set."""
    normalized = normalize_api_token_scopes(scopes)
    for profile_id, profile_scopes in API_TOKEN_PERMISSION_PROFILES.items():
        if normalized == list(profile_scopes):
            return profile_id
    return None


def list_api_token_permission_profiles(*, include_administrator: bool) -> list[dict[str, Any]]:
    """Expose selectable profiles without duplicating scope definitions in clients."""
    profiles: list[dict[str, Any]] = []
    for profile_id, scopes in API_TOKEN_PERMISSION_PROFILES.items():
        if profile_id == "administrator" and not include_administrator:
            continue
        profiles.append({"id": profile_id, "scopes": list(scopes)})
    return profiles


def _api_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _api_token_plaintext() -> str:
    return f"ohs_{secrets.token_urlsafe(32)}"


def _api_token_scopes(token: ApiToken) -> list[str]:
    try:
        decoded = json.loads(token.scopes or "[]")
    except (TypeError, ValueError):
        decoded = []
    return normalize_api_token_scopes(decoded)


def init_auth(
    create_default_admin: bool = False,
    *,
    database_url: Optional[str] = None,
    allow_sqlite_for_tests: bool = False,
) -> bool:
    """
    Initialize authentication system and database.
    Creates default admin user if database is empty.
    """
    global db_session

    from core.database_connection import (
        is_postgresql_url,
        resolve_application_database_url,
    )
    from core.database_migrations import upgrade_database

    with _auth_cleanup_lock:
        if _auth_cleanup_pending is not None:
            raise RuntimeError(
                "Cleanup autenticazione incompleto: ripetere lo shutdown prima dell'inizializzazione."
            )

        # Authentication and application data share one PostgreSQL database.
        db_url = database_url or resolve_application_database_url()
        if not db_url:
            db_session = None
            print("[AUTH] Database PostgreSQL non configurato: autenticazione in attesa del setup.")
            return False
        if not allow_sqlite_for_tests and not is_postgresql_url(db_url):
            raise RuntimeError("Configura OCTOHUBS_DB_URL con un database PostgreSQL.")

        upgrade_database(db_url)

        # Publish only after migration and registry construction complete while
        # shutdown is excluded by the same lifecycle lock.
        engine = create_engine(db_url, echo=False, **postgres_engine_options(db_url))
        session_factory = sessionmaker(bind=engine)
        db_session = RequestAwareSessionRegistry(session_factory)

        # Create default admin user if none exists
        if create_default_admin:
            _create_default_admin()

    print("[AUTH] Sistema di autenticazione inizializzato (database PostgreSQL condiviso)")
    return True


def shutdown_auth() -> bool:
    """Close every auth resource, preserving deterministic best-effort shutdown."""
    global db_session, _auth_cleanup_pending

    with _auth_cleanup_lock:
        registry = db_session
        db_session = None
        if registry is not None:
            _auth_cleanup_pending = registry
        else:
            registry = _auth_cleanup_pending
        if registry is None:
            return True

        engine = registry.session_factory.kw.get("bind")
        cleaned = True
        try:
            if registry.close_all() is False:
                cleaned = False
        except Exception as exc:
            cleaned = False
            logger.error(
                "[AUTH] Chiusura delle sessioni non riuscita:\n%s",
                format_exception_for_log(exc),
            )
        finally:
            if engine is not None:
                try:
                    if not dispose_engine_safely(engine, context="auth pool"):
                        cleaned = False
                except Exception as exc:
                    cleaned = False
                    logger.error(
                        "[AUTH] Chiusura del pool non riuscita:\n%s",
                        format_exception_for_log(exc),
                    )
        if cleaned:
            _auth_cleanup_pending = None
        return cleaned


def _create_default_admin():
    """Create default admin user if database is empty."""
    try:
        assert db_session is not None, "Database session not initialized"
        user_count = db_session.query(User).count()
        if user_count == 0:
            def _read_env_secret(key: str) -> Optional[str]:
                file_key = f"{key}_FILE"
                file_path = os.environ.get(file_key)
                if file_path:
                    try:
                        with open(file_path, "r") as handle:
                            value = handle.read().strip()
                        if value:
                            return value
                    except OSError:
                        pass
                value = os.environ.get(key)
                if isinstance(value, str):
                    value = value.strip()
                return value or None

            admin_username = (os.environ.get('ADMIN_USERNAME') or "").strip()
            admin_password = _read_env_secret('ADMIN_PASSWORD')
            admin_email = (os.environ.get('ADMIN_EMAIL') or "").strip() or None

            if not admin_username or not admin_password:
                return
            if is_public_admin_bootstrap_password(admin_password):
                print(
                    "[AUTH] Amministratore iniziale non creato: "
                    "la password coincide con un esempio pubblico; configurane una univoca."
                )
                return

            admin = User(
                username=admin_username,
                email=admin_email or "admin@localhost",
                is_active=True,
                is_admin=True,
                role="admin"
            )
            try:
                admin.set_password(admin_password)
            except PasswordTooLongError as exc:
                logger.error("[AUTH] Amministratore iniziale non creato:\n%s", format_exception_for_log(exc))
                return

            db_session.add(admin)
            db_session.commit()

            print(f"[AUTH] Utente amministratore creato: {admin_username}")
            print("[AUTH] ATTENZIONE: Cambia la password di default!")
    except SQLAlchemyError as e:
        _log_auth_exception("Errore durante la creazione dell'admin", e)
        assert db_session is not None
        _rollback_safely(db_session)
        raise AuthStorageError("Bootstrap amministratore non disponibile") from e


def get_user_by_username(username: str) -> Optional[User]:
    """Get user by username."""
    try:
        assert db_session is not None
        return db_session.query(User).filter_by(username=username).first()
    except SQLAlchemyError as exc:
        raise AuthStorageError("Lettura account non disponibile") from exc


def get_user_by_id(user_id: int) -> Optional[User]:
    """Get user by ID."""
    try:
        assert db_session is not None
        return db_session.get(User, user_id)
    except ValueError:
        return None
    except SQLAlchemyError as exc:
        raise AuthStorageError("Lettura account non disponibile") from exc


def create_user(username: str, password: str, email: Optional[str] = None,
                is_admin: bool = False, role: Optional[str] = None) -> Optional[User]:
    """
    Create a new user.
    Returns User object if successful, None otherwise.
    """
    try:
        bcrypt_password_bytes(password)
    except (TypeError, PasswordTooLongError) as exc:
        logger.error("[AUTH] Utente non creato:\n%s", format_exception_for_log(exc))
        return None

    try:
        # Check if username already exists
        existing = get_user_by_username(username)
        if existing:
            print(f"[AUTH] Utente '{username}' già esistente")
            return None

        assert db_session is not None
        normalized_role = _normalize_role(role, is_admin)
        user = User(
            username=username,
            email=email,
            is_active=True,
            is_admin=normalized_role == "admin",
            role=normalized_role
        )
        user.set_password(password)

        db_session.add(user)
        db_session.commit()

        print(f"[AUTH] Utente creato: {username} (ruolo: {normalized_role})")
        return user
    except IntegrityError as e:
        _log_auth_exception("Errore durante la creazione dell'utente", e)
        assert db_session is not None
        _rollback_safely(db_session)
        return None
    except SQLAlchemyError as e:
        assert db_session is not None
        _rollback_safely(db_session)
        raise AuthStorageError("Creazione account non disponibile") from e


def update_user_password(user: User, new_password: str) -> bool:
    """Update user password."""
    try:
        password_bytes = bcrypt_password_bytes(new_password)
    except (TypeError, PasswordTooLongError) as exc:
        logger.error("[AUTH] Password non aggiornata:\n%s", format_exception_for_log(exc))
        return False

    try:
        assert db_session is not None
        # Hash before opening the row-locking transaction: bcrypt is deliberately
        # expensive and must not hold an account row lock while it runs.
        password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")
        session = db_session()
        # The route hashes in a worker thread, whose scoped session differs
        # from the request's ORM instance. Merge and lock the managed row so
        # concurrent changes serialize without relying on a stale instance.
        managed_user = session.merge(user)
        session.refresh(managed_user, with_for_update=True)
        managed_user.password_hash = password_hash
        managed_user.auth_epoch = int(getattr(managed_user, "auth_epoch", 0) or 0) + 1
        session.commit()
        user.password_hash = managed_user.password_hash
        user.auth_epoch = managed_user.auth_epoch
        print(f"[AUTH] Password aggiornata per: {user.username}")
        return True
    except SQLAlchemyError as e:
        _log_auth_exception("Errore durante l'aggiornamento della password", e)
        assert db_session is not None
        _rollback_safely(db_session)
        raise AuthStorageError("Aggiornamento password non disponibile") from e


def update_user_details(user: User, *, email: str | None | object = _UNSET,
                        role: Optional[str] = None, is_active: Optional[bool] = None) -> bool:
    """Update the safe, non-secret properties of a login account."""
    try:
        assert db_session is not None
        session = db_session()
        with active_admin_mutation_guard(session):
            session.refresh(user)
            previous_role = user.get_role()
            previous_active = bool(user.is_active)
            next_role = _normalize_role(role) if role is not None else user.get_role()
            next_active = bool(user.is_active) if is_active is None else bool(is_active)

            if user.get_role() == "admin" and (next_role != "admin" or not next_active):
                remaining_admins = session.query(User).filter(
                    User.id != user.id,
                    User.is_active.is_(True),
                    User.is_admin.is_(True),
                ).count()
                if remaining_admins == 0:
                    print("[AUTH] Impossibile rimuovere o disattivare l'ultimo amministratore attivo")
                    _rollback_safely(session)
                    return False

            if email is not _UNSET:
                normalized_email = str(email).strip() or None
                if normalized_email:
                    duplicate = session.query(User).filter(
                        User.email == normalized_email,
                        User.id != user.id,
                    ).first()
                    if duplicate is not None:
                        print(f"[AUTH] Email gia in uso: {normalized_email}")
                        _rollback_safely(session)
                        return False
                user.email = normalized_email
            user.set_role(next_role)
            user.is_active = next_active
            if previous_role != next_role or previous_active != next_active:
                user.auth_epoch = int(getattr(user, "auth_epoch", 0) or 0) + 1
            session.commit()
            return True
    except SQLAlchemyError as e:
        _log_auth_exception("Errore durante l'aggiornamento dell'utente", e)
        assert db_session is not None
        _rollback_safely(db_session)
        raise AuthStorageError("Aggiornamento account non disponibile") from e


def update_user_account(
    user: User,
    *,
    email: str | None | object = _UNSET,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    password: str | object = _UNSET,
) -> bool:
    """Apply one administrative account patch in a single transaction."""
    password_hash: str | None = None
    if password is not _UNSET:
        try:
            if not isinstance(password, str):
                raise TypeError("La password deve essere una stringa")
            password_bytes = bcrypt_password_bytes(password)
            password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")
        except (TypeError, PasswordTooLongError) as exc:
            _log_auth_exception("Password account non valida", exc)
            return False

    try:
        assert db_session is not None
        session = db_session()
        with active_admin_mutation_guard(session):
            managed_user = session.merge(user)
            session.refresh(managed_user, with_for_update=True)
            previous_role = managed_user.get_role()
            previous_active = bool(managed_user.is_active)
            next_role = _normalize_role(role) if role is not None else previous_role
            next_active = previous_active if is_active is None else bool(is_active)

            if previous_role == "admin" and (next_role != "admin" or not next_active):
                remaining_admins = session.query(User).filter(
                    User.id != managed_user.id,
                    User.is_active.is_(True),
                    User.is_admin.is_(True),
                ).count()
                if remaining_admins == 0:
                    _rollback_safely(session)
                    return False

            if email is not _UNSET:
                normalized_email = str(email).strip() or None
                if normalized_email:
                    duplicate = session.query(User).filter(
                        User.email == normalized_email,
                        User.id != managed_user.id,
                    ).first()
                    if duplicate is not None:
                        _rollback_safely(session)
                        return False
                managed_user.email = normalized_email

            managed_user.set_role(next_role)
            managed_user.is_active = next_active
            authorization_changed = (
                previous_role != next_role
                or previous_active != next_active
                or password_hash is not None
            )
            if password_hash is not None:
                managed_user.password_hash = password_hash
            if authorization_changed:
                managed_user.auth_epoch = int(getattr(managed_user, "auth_epoch", 0) or 0) + 1

            session.commit()
            user.email = managed_user.email
            user.set_role(managed_user.get_role())
            user.is_active = managed_user.is_active
            user.password_hash = managed_user.password_hash
            user.auth_epoch = managed_user.auth_epoch
            return True
    except SQLAlchemyError as exc:
        _log_auth_exception("Errore durante l'aggiornamento atomico dell'account", exc)
        assert db_session is not None
        _rollback_safely(db_session)
        raise AccountUpdateStorageError("Aggiornamento account non disponibile") from exc


def delete_user(user: User) -> bool:
    """Delete a user (cannot delete the last active administrator)."""
    try:
        assert db_session is not None
        session = db_session()
        with active_admin_mutation_guard(session):
            session.refresh(user)
            if user.get_role() == "admin" and bool(user.is_active):
                remaining_admins = session.query(User).filter(
                    User.id != user.id,
                    User.is_active.is_(True),
                    User.is_admin.is_(True),
                ).count()
                if remaining_admins == 0:
                    print("[AUTH] Impossibile eliminare l'ultimo amministratore attivo")
                    _rollback_safely(session)
                    return False

            username = str(user.username)
            session.query(ApiToken).filter_by(user_id=user.id).delete()
            session.query(UserInterfacePreference).filter_by(user_id=user.id).delete()
            session.delete(user)
            session.commit()
            print(f"[AUTH] Utente eliminato: {username}")
            return True
    except SQLAlchemyError as e:
        _log_auth_exception("Errore durante l'eliminazione dell'utente", e)
        assert db_session is not None
        _rollback_safely(db_session)
        raise AuthStorageError("Eliminazione account non disponibile") from e


def get_all_users():
    """Get all users."""
    try:
        assert db_session is not None
        return db_session.query(User).order_by(User.username).all()
    except SQLAlchemyError as exc:
        raise AuthStorageError("Elenco account non disponibile") from exc


def has_users() -> bool:
    """Return whether any account exists without materializing the user table."""
    try:
        assert db_session is not None
        return db_session.query(User.id).first() is not None
    except SQLAlchemyError as exc:
        raise AuthStorageError("Verifica account non disponibile") from exc


def _api_token_expiry(value: Any) -> datetime | None | object:
    """Turn a bounded expiry in days into a UTC timestamp, or reject invalid input."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return _UNSET
    try:
        days = int(value)
    except (TypeError, ValueError):
        return _UNSET
    if days < 1 or days > 3650:
        return _UNSET
    return _utcnow() + timedelta(days=days)


def _api_token_is_expired(token: ApiToken, *, now: datetime | None = None) -> bool:
    expires_at = getattr(token, "expires_at", None)
    return bool(expires_at and expires_at <= (now or _utcnow()))


def _new_api_token(user_id: int, name: str, scopes: list[str], expires_at: datetime | None) -> tuple[ApiToken, str]:
    plaintext = _api_token_plaintext()
    return (
        ApiToken(
            user_id=int(user_id),
            name=name[:120],
            token_hash=_api_token_hash(plaintext),
            token_prefix=plaintext[:12],
            scopes=json.dumps(scopes, separators=(",", ":")),
            is_active=True,
            expires_at=expires_at,
        ),
        plaintext,
    )


def _lock_api_token_owner(user_id: int) -> User | None:
    assert db_session is not None
    return (
        db_session.query(User)
        .filter(User.id == int(user_id))
        .with_for_update()
        .one_or_none()
    )


def _active_api_token_count(user_id: int, now: datetime) -> int:
    assert db_session is not None
    return int(
        db_session.query(ApiToken)
        .filter(
            ApiToken.user_id == int(user_id),
            ApiToken.is_active.is_(True),
            or_(ApiToken.expires_at.is_(None), ApiToken.expires_at > now),
        )
        .count()
    )


def _prune_api_token_history(user_id: int, now: datetime) -> None:
    """Bound revoked/expired token rows while retaining all active credentials."""
    assert db_session is not None
    stale_ids = [
        int(row.id)
        for row in (
            db_session.query(ApiToken.id)
            .filter(
                ApiToken.user_id == int(user_id),
                or_(ApiToken.is_active.is_(False), ApiToken.expires_at <= now),
            )
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
            .offset(API_TOKEN_MAX_HISTORY_PER_ACCOUNT)
            .all()
        )
    ]
    if stale_ids:
        db_session.query(ApiToken).filter(ApiToken.id.in_(stale_ids)).delete(
            synchronize_session=False
        )


def create_api_token(
    user: User,
    name: str,
    scopes: Any,
    *,
    expires_in_days: Any = None,
) -> Optional[tuple[ApiToken, str]]:
    """Create an API token for an active user and return its one-time plaintext value."""
    normalized_name = str(name or "").strip()
    normalized_scopes = normalize_api_token_scopes(scopes)
    expires_at = _api_token_expiry(expires_in_days)
    if not normalized_name or not normalized_scopes or expires_at is _UNSET or not db_session:
        return None
    try:
        if _lock_api_token_owner(int(user.id)) is None:
            _rollback_safely(db_session)
            return None
        now = _utcnow()
        if _active_api_token_count(int(user.id), now) >= API_TOKEN_MAX_ACTIVE_PER_ACCOUNT:
            _rollback_safely(db_session)
            return None
        token, plaintext = _new_api_token(int(user.id), normalized_name, normalized_scopes, expires_at)
        db_session.add(token)
        _prune_api_token_history(int(user.id), now)
        db_session.commit()
        return token, plaintext
    except SQLAlchemyError as e:
        _log_auth_exception("Errore durante creazione API token", e)
        assert db_session is not None
        _rollback_safely(db_session)
        raise AuthStorageError("Creazione API token non disponibile") from e


def list_api_tokens(user_id: int) -> list[ApiToken]:
    """List API tokens owned by one account without exposing their secret value."""
    if not db_session:
        return []
    try:
        assert db_session is not None
        return (
            db_session.query(ApiToken)
            .filter_by(user_id=int(user_id))
            .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
            .limit(API_TOKEN_MAX_LISTED_PER_ACCOUNT)
            .all()
        )
    except ValueError:
        return []
    except SQLAlchemyError as exc:
        raise AuthStorageError("Elenco API token non disponibile") from exc


def revoke_api_token(user_id: int, token_id: int) -> bool:
    """Disable one API token owned by the current account."""
    if not db_session:
        return False
    try:
        assert db_session is not None
        if _lock_api_token_owner(int(user_id)) is None:
            _rollback_safely(db_session)
            return False
        token = db_session.query(ApiToken).filter_by(id=int(token_id), user_id=int(user_id)).first()
        if token is None or not bool(token.is_active) or _api_token_is_expired(token):
            return False
        token.is_active = False
        token.revoked_at = _utcnow()
        _prune_api_token_history(int(user_id), _utcnow())
        db_session.commit()
        return True
    except ValueError as error:
        _log_auth_exception("Errore durante revoca API token", error)
        assert db_session is not None
        _rollback_safely(db_session)
        return False
    except SQLAlchemyError as error:
        assert db_session is not None
        _rollback_safely(db_session)
        raise AuthStorageError("Revoca API token non disponibile") from error


def rotate_api_token(user_id: int, token_id: int) -> Optional[tuple[ApiToken, str]]:
    """Replace one active, unexpired token without ever recovering its secret."""
    if not db_session:
        return None
    try:
        assert db_session is not None
        if _lock_api_token_owner(int(user_id)) is None:
            _rollback_safely(db_session)
            return None
        token = db_session.query(ApiToken).filter_by(id=int(token_id), user_id=int(user_id)).first()
        if token is None or not bool(token.is_active) or _api_token_is_expired(token):
            return None
        replacement, plaintext = _new_api_token(
            int(user_id),
            str(token.name or ""),
            _api_token_scopes(token),
            getattr(token, "expires_at", None),
        )
        token.is_active = False
        token.revoked_at = _utcnow()
        db_session.add(replacement)
        _prune_api_token_history(int(user_id), _utcnow())
        db_session.commit()
        return replacement, plaintext
    except ValueError as error:
        _log_auth_exception("Errore durante rotazione API token", error)
        assert db_session is not None
        _rollback_safely(db_session)
        return None
    except SQLAlchemyError as error:
        assert db_session is not None
        _rollback_safely(db_session)
        raise AuthStorageError("Rotazione API token non disponibile") from error


def verify_api_token(plaintext: str) -> Optional[dict[str, Any]]:
    """Resolve a Bearer token to an active user and its scopes."""
    token_value = str(plaintext or "").strip()
    if not token_value or not db_session:
        return None
    try:
        assert db_session is not None
        token = db_session.query(ApiToken).filter_by(token_hash=_api_token_hash(token_value)).first()
        if token is None or not bool(token.is_active) or _api_token_is_expired(token):
            return None
        user = get_user_by_id(int(token.user_id))
        if user is None or not bool(user.is_active):
            return None
        now = _utcnow()
        if token.last_used_at is None or now - token.last_used_at >= _API_TOKEN_LAST_USED_INTERVAL:
            token.last_used_at = now
            db_session.commit()
        return {"user": user, "token": token, "scopes": _api_token_scopes(token)}
    except ValueError:
        if db_session:
            _rollback_safely(db_session)
        return None
    except SQLAlchemyError as exc:
        if db_session:
            _rollback_safely(db_session)
        raise AuthStorageError("Verifica API token non disponibile") from exc


def normalize_interface_preferences(preferences: Optional[Mapping[str, Any]]) -> dict[str, str]:
    """Return the supported layout preferences, falling back to stable defaults."""
    source = preferences or {}
    primary = str(source.get("primary_navigation") or "").strip().lower()
    secondary = str(source.get("secondary_navigation") or "").strip().lower()
    return {
        "primary_navigation": primary if primary in PRIMARY_NAVIGATION_MODES else DEFAULT_INTERFACE_PREFERENCES["primary_navigation"],
        "secondary_navigation": secondary if secondary in SECONDARY_NAVIGATION_MODES else DEFAULT_INTERFACE_PREFERENCES["secondary_navigation"],
    }


def _normalize_navigation_order_page(value: Any) -> Optional[str]:
    page = str(value or "").strip()
    if not page or len(page) > 80:
        return None
    return page


def _normalize_navigation_orders(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, list[str]] = {}
    for raw_page, raw_order in value.items():
        page = _normalize_navigation_order_page(raw_page)
        if page is None or not isinstance(raw_order, list) or len(normalized) >= 16:
            continue
        seen: set[str] = set()
        entries: list[str] = []
        for raw_item in raw_order[:64]:
            item = str(raw_item or "").strip()
            if not item or len(item) > 100 or item in seen:
                continue
            seen.add(item)
            entries.append(item)
        normalized[page] = entries
    return normalized


def _navigation_orders_from_preference(preference: UserInterfacePreference) -> dict[str, list[str]]:
    raw_orders = getattr(preference, "navigation_order", "{}") or "{}"
    try:
        decoded = json.loads(raw_orders)
    except (TypeError, ValueError):
        decoded = {}
    return _normalize_navigation_orders(decoded)


def get_user_interface_preferences(user_id: int) -> dict[str, str]:
    """Load a user's workspace layout, distinguishing invalid input from DB outage."""
    if not db_session:
        return dict(DEFAULT_INTERFACE_PREFERENCES)
    try:
        preference = db_session.query(UserInterfacePreference).filter_by(user_id=user_id).first()
        if preference is None:
            return dict(DEFAULT_INTERFACE_PREFERENCES)
        return normalize_interface_preferences(
            {
                "primary_navigation": preference.primary_navigation,
                "secondary_navigation": preference.secondary_navigation,
            }
        )
    except ValueError:
        return dict(DEFAULT_INTERFACE_PREFERENCES)
    except SQLAlchemyError as exc:
        raise AuthStorageError("Lettura preferenze non disponibile") from exc


def get_user_interface_order(user_id: int, page: str) -> Optional[list[str]]:
    """Load one personal navigation order from the authenticated user's profile."""
    normalized_page = _normalize_navigation_order_page(page)
    if normalized_page is None or not db_session:
        return None
    try:
        preference = db_session.query(UserInterfacePreference).filter_by(user_id=user_id).first()
        if preference is None:
            return None
        orders = _navigation_orders_from_preference(preference)
        current_order = orders.get(normalized_page)
        return list(current_order) if current_order is not None else None
    except ValueError:
        return None
    except SQLAlchemyError as exc:
        raise AuthStorageError("Lettura ordine interfaccia non disponibile") from exc


def _lock_user_interface_preference(user_id: int) -> None:
    """Serialize creation and updates of one user's shared preference row."""
    if db_session and db_session.get_bind().dialect.name == "postgresql":
        db_session.execute(
            text("SELECT pg_advisory_xact_lock(1868787064, :user_id)"),
            {"user_id": int(user_id)},
        )


def _normalized_interface_preference_updates(
    preferences: Mapping[str, Any],
) -> Optional[dict[str, str]]:
    updates: dict[str, str] = {}
    modes = {
        "primary_navigation": PRIMARY_NAVIGATION_MODES,
        "secondary_navigation": SECONDARY_NAVIGATION_MODES,
    }
    for field, allowed in modes.items():
        if field not in preferences:
            continue
        value = str(preferences.get(field) or "").strip().lower()
        if value not in allowed:
            return None
        updates[field] = value
    return updates


def save_user_interface_preferences(user_id: int, preferences: Mapping[str, Any]) -> Optional[dict[str, str]]:
    """Atomically merge supplied layout fields into one user's current value."""
    updates = _normalized_interface_preference_updates(preferences)
    if updates is None or not db_session:
        return None
    with _interface_preferences_write_lock:
        try:
            _lock_user_interface_preference(user_id)
            preference = (
                db_session.query(UserInterfacePreference)
                .filter_by(user_id=user_id)
                .with_for_update()
                .first()
            )
            current = normalize_interface_preferences(
                {
                    "primary_navigation": getattr(preference, "primary_navigation", None),
                    "secondary_navigation": getattr(preference, "secondary_navigation", None),
                }
                if preference is not None
                else None
            )
            normalized = {**current, **updates}
            if preference is None:
                preference = UserInterfacePreference(user_id=user_id, **normalized)
                db_session.add(preference)
            else:
                preference.primary_navigation = normalized["primary_navigation"]
                preference.secondary_navigation = normalized["secondary_navigation"]
            db_session.commit()
            return normalized
        except ValueError:
            if db_session:
                _rollback_safely(db_session)
            return None
        except SQLAlchemyError as exc:
            if db_session:
                _rollback_safely(db_session)
            raise AuthStorageError("Salvataggio preferenze non disponibile") from exc


def save_user_interface_order(user_id: int, page: str, order: Any) -> Optional[list[str]]:
    """Persist one personal navigation sequence without touching shared operational data."""
    normalized_page = _normalize_navigation_order_page(page)
    normalized_orders = _normalize_navigation_orders({normalized_page: order}) if normalized_page else {}
    if normalized_page is None or normalized_page not in normalized_orders or not db_session:
        return None
    with _interface_preferences_write_lock:
        try:
            _lock_user_interface_preference(user_id)
            preference = (
                db_session.query(UserInterfacePreference)
                .filter_by(user_id=user_id)
                .with_for_update()
                .first()
            )
            if preference is None:
                preference = UserInterfacePreference(user_id=user_id, **DEFAULT_INTERFACE_PREFERENCES)
                db_session.add(preference)
            orders = _navigation_orders_from_preference(preference)
            orders[normalized_page] = normalized_orders[normalized_page]
            preference.navigation_order = json.dumps(orders, separators=(",", ":"), sort_keys=True)
            db_session.commit()
            return list(orders[normalized_page])
        except (TypeError, ValueError):
            if db_session:
                _rollback_safely(db_session)
            return None
        except SQLAlchemyError as exc:
            if db_session:
                _rollback_safely(db_session)
            raise AuthStorageError("Salvataggio ordine interfaccia non disponibile") from exc


def toggle_user_active(user: User) -> bool:
    """Toggle user active status."""
    next_active = not bool(user.is_active)
    updated = update_user_details(user, is_active=next_active)
    if updated:
        status = "attivo" if next_active else "disabilitato"
        print(f"[AUTH] Utente {user.username} ora è {status}")
    return updated


def set_user_role(user: User, role: str) -> bool:
    """Set user role (admin/user/viewer)."""
    updated = update_user_details(user, role=role)
    if updated:
        print(f"[AUTH] Ruolo aggiornato per {user.username}: {user.get_role()}")
    return updated


def log_audit_event(user: Optional[Any], action: str, detail: Optional[str] = None,
                    request_obj=None) -> None:
    """Store an audit log entry for a user action."""
    if not db_session:
        return
    username = getattr(user, "username", None) if user else None
    user_id = getattr(user, "id", None) if user else None
    ip_address = None
    path = None
    method = None
    user_agent = None
    if request_obj is not None:
        try:
            headers = getattr(request_obj, "headers", {}) or {}
            url = getattr(request_obj, "url", None)
            scope = getattr(request_obj, "scope", {}) or {}
            ip_address = resolve_client_address(request_obj)
            externally_versioned_path = (
                scope.get("octohubs_external_path") if isinstance(scope, dict) else None
            )
            path = externally_versioned_path or getattr(request_obj, "path", None) or getattr(url, "path", None)
            if path is None:
                if isinstance(scope, dict):
                    path = scope.get("path")
            method = getattr(request_obj, "method", None)
            user_agent = headers.get("User-Agent")
        except Exception:
            pass
    username = str(username or "")[:80] or None
    action = str(action or "")[:120]
    ip_address = str(ip_address or "")[:64] or None
    path = str(path or "")[:255] or None
    method = str(method or "")[:10] or None
    user_agent = str(user_agent or "")[:255] or None
    try:
        assert db_session is not None
        global _last_audit_prune_at
        now_monotonic = time.monotonic()
        prune = False
        with _audit_state_lock:
            if now_monotonic - _last_audit_prune_at >= 3600:
                _last_audit_prune_at = now_monotonic
                prune = True
        if prune:
            db_session.query(AuditLog).filter(
                AuditLog.created_at < _utcnow() - timedelta(days=_AUDIT_RETENTION_DAYS)
            ).delete(synchronize_session=False)
        entry = AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            detail=detail,
            ip_address=ip_address,
            path=path,
            method=method,
            user_agent=user_agent
        )
        db_session.add(entry)
        db_session.commit()
    except SQLAlchemyError as e:
        _log_auth_exception("Errore durante audit log", e)
        assert db_session is not None
        _rollback_safely(db_session)


def log_api_token_usage(
    user: Optional[Any],
    token: Optional[Any],
    scopes: list[str],
    required_scope: str,
    request_obj=None,
    *,
    allowed: bool,
) -> None:
    """Store a safe audit entry for external API token usage."""
    method = str(getattr(request_obj, "method", "") or "").upper()
    if not allowed:
        action = "api_token_denied"
    elif required_scope == "run:operations":
        action = "api_token_operation"
    elif method in {"GET", "HEAD", "OPTIONS"}:
        action = "api_token_read"
    else:
        action = "api_token_write"

    token_id = int(getattr(token, "id", 0) or 0)
    if action == "api_token_read":
        url = getattr(request_obj, "url", None)
        path = str(
            getattr(url, "path", None)
            or getattr(request_obj, "path", "")
            or (getattr(request_obj, "scope", {}) or {}).get("path", "")
        )
        token_prefix = str(getattr(token, "token_prefix", "") or "")
        key = (token_id, token_prefix, method, path[:255])
        now = time.monotonic()
        with _audit_state_lock:
            last_seen = _recent_read_audits.get(key)
            if last_seen is not None and now - last_seen < _API_TOKEN_READ_AUDIT_INTERVAL_SECONDS:
                return
            _recent_read_audits[key] = now
            if len(_recent_read_audits) > 10_000:
                cutoff = now - _API_TOKEN_READ_AUDIT_INTERVAL_SECONDS
                stale = [entry for entry, seen_at in _recent_read_audits.items() if seen_at < cutoff]
                for entry in stale:
                    _recent_read_audits.pop(entry, None)
                overflow = len(_recent_read_audits) - 10_000
                if overflow > 0:
                    oldest = sorted(
                        _recent_read_audits,
                        key=_recent_read_audits.__getitem__,
                    )[:overflow]
                    for entry in oldest:
                        _recent_read_audits.pop(entry, None)

    detail = json.dumps(
        {
            "token_id": token_id,
            "token_name": str(getattr(token, "name", "") or ""),
            "token_prefix": str(getattr(token, "token_prefix", "") or ""),
            "required_scope": required_scope,
            "granted_scopes": normalize_api_token_scopes(scopes),
            "result": "allowed" if allowed else "denied",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    log_audit_event(user, action, detail, request_obj)


def get_audit_logs(limit: int = 100):
    """Return recent audit logs."""
    if not db_session:
        return []
    try:
        assert db_session is not None
        return (db_session.query(AuditLog)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .all())
    except SQLAlchemyError as exc:
        raise AuthStorageError("Elenco audit non disponibile") from exc


def get_api_token_audit_summaries(user_id: int, *, limit: int = 500) -> dict[int, dict[str, Any]]:
    """Return the latest audited API-token action for each token owned by one user."""
    if not db_session:
        return {}
    try:
        assert db_session is not None
        entries = (
            db_session.query(AuditLog)
            .filter(AuditLog.user_id == int(user_id))
            .filter(AuditLog.action.in_(["api_token_read", "api_token_write", "api_token_operation", "api_token_denied"]))
            .order_by(AuditLog.created_at.desc())
            .limit(max(1, min(int(limit), 2000)))
            .all()
        )
    except ValueError:
        return {}
    except SQLAlchemyError as exc:
        raise AuthStorageError("Riepilogo audit token non disponibile") from exc

    summaries: dict[int, dict[str, Any]] = {}
    for entry in entries:
        try:
            detail = json.loads(entry.detail or "{}")
        except (TypeError, ValueError):
            detail = {}
        token_id = int(detail.get("token_id") or 0)
        if token_id <= 0 or token_id in summaries:
            continue
        summaries[token_id] = {
            "action": str(entry.action or ""),
            "at": entry.created_at.isoformat() if hasattr(entry.created_at, "isoformat") else None,
            "method": str(entry.method or ""),
            "path": str(entry.path or ""),
            "required_scope": str(detail.get("required_scope") or ""),
            "result": str(detail.get("result") or ""),
        }
    return summaries
