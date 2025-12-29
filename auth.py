"""
Authentication module with Flask-Login and SQLAlchemy.
Manages user accounts, password hashing, and session management.
"""
import os
from datetime import datetime
from typing import Optional, Any

from flask import Flask, jsonify, redirect, request, url_for
from flask_login import LoginManager, UserMixin
from flask_bcrypt import Bcrypt
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from sqlalchemy.exc import SQLAlchemyError

# SQLAlchemy setup
Base = declarative_base()
bcrypt = Bcrypt()
login_manager = LoginManager()

# Database session
db_session = None

ROLE_VALUES = ("admin", "user", "viewer")


class User(Base, UserMixin):
    """User model for authentication."""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(120), unique=True, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    role = Column(String(20), default="user", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)

    def set_password(self, password: str):
        """Hash and set the user password."""
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password: str) -> bool:
        """Verify password against hash."""
        return bcrypt.check_password_hash(self.password_hash, password)

    def update_last_login(self):
        """Update last login timestamp."""
        self.last_login = datetime.utcnow()
        if db_session:
            try:
                db_session.commit()
            except SQLAlchemyError:
                db_session.rollback()

    def get_role(self) -> str:
        """Return normalized role for the user."""
        if self.is_admin:
            return "admin"
        if self.role in ROLE_VALUES:
            return self.role
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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


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


def init_auth(app: Flask):
    """
    Initialize authentication system with Flask-Login and database.
    Creates default admin user if database is empty.
    """
    global db_session

    # Initialize Flask extensions
    bcrypt.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth_login'
    login_manager.login_message = 'Devi effettuare il login per accedere a questa pagina.'
    login_manager.login_message_category = 'warning'
    login_manager.session_protection = 'strong'

    @login_manager.unauthorized_handler
    def _unauthorized():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"success": False, "message": "Sessione scaduta. Ricarica la pagina."}), 401
        return redirect(url_for('auth_login'))

    # Database configuration
    db_url = os.environ.get('AUTH_DATABASE_URL')
    if not db_url:
        # Use SQLite by default for simplicity
        db_url = 'sqlite:///auth.db'

    # Create engine and session
    engine = create_engine(db_url, echo=False)
    session_factory = sessionmaker(bind=engine)
    db_session = scoped_session(session_factory)

    # Create tables
    Base.metadata.create_all(engine)
    _ensure_schema(engine)

    # Create default admin user if none exists
    _create_default_admin()

    # Register teardown handler
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if db_session:
            db_session.remove()

    print(f"[AUTH] Sistema di autenticazione inizializzato (database: {db_url})")


def _create_default_admin():
    """Create default admin user if database is empty."""
    try:
        user_count = db_session.query(User).count()
        if user_count == 0:
            # Get credentials from environment or use defaults
            admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
            admin_password = os.environ.get('ADMIN_PASSWORD', 'admin')
            admin_email = os.environ.get('ADMIN_EMAIL', 'admin@localhost')

            admin = User(
                username=admin_username,
                email=admin_email,
                is_active=True,
                is_admin=True,
                role="admin"
            )
            admin.set_password(admin_password)

            db_session.add(admin)
            db_session.commit()

            print(f"[AUTH] Utente amministratore creato: {admin_username}")
            print(f"[AUTH] ATTENZIONE: Cambia la password di default!")
    except SQLAlchemyError as e:
        print(f"[AUTH] Errore durante la creazione dell'admin: {e}")
        db_session.rollback()


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    """Load user by ID for Flask-Login."""
    try:
        return db_session.query(User).get(int(user_id))
    except (ValueError, SQLAlchemyError):
        return None


def get_user_by_username(username: str) -> Optional[User]:
    """Get user by username."""
    try:
        return db_session.query(User).filter_by(username=username).first()
    except SQLAlchemyError:
        return None


def create_user(username: str, password: str, email: Optional[str] = None,
                is_admin: bool = False, role: Optional[str] = None) -> Optional[User]:
    """
    Create a new user.
    Returns User object if successful, None otherwise.
    """
    try:
        # Check if username already exists
        existing = get_user_by_username(username)
        if existing:
            print(f"[AUTH] Utente '{username}' già esistente")
            return None

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
    except SQLAlchemyError as e:
        print(f"[AUTH] Errore durante la creazione dell'utente: {e}")
        db_session.rollback()
        return None


def update_user_password(user: User, new_password: str) -> bool:
    """Update user password."""
    try:
        user.set_password(new_password)
        db_session.commit()
        print(f"[AUTH] Password aggiornata per: {user.username}")
        return True
    except SQLAlchemyError as e:
        print(f"[AUTH] Errore durante l'aggiornamento della password: {e}")
        db_session.rollback()
        return False


def delete_user(user: User) -> bool:
    """Delete a user (cannot delete last admin)."""
    try:
        # Check if this is the last admin
        if user.is_admin:
            admin_count = db_session.query(User).filter_by(is_admin=True).count()
            if admin_count <= 1:
                print("[AUTH] Impossibile eliminare l'ultimo amministratore")
                return False

        db_session.delete(user)
        db_session.commit()
        print(f"[AUTH] Utente eliminato: {user.username}")
        return True
    except SQLAlchemyError as e:
        print(f"[AUTH] Errore durante l'eliminazione dell'utente: {e}")
        db_session.rollback()
        return False


def get_all_users():
    """Get all users."""
    try:
        return db_session.query(User).order_by(User.username).all()
    except SQLAlchemyError:
        return []


def toggle_user_active(user: User) -> bool:
    """Toggle user active status."""
    try:
        user.is_active = not user.is_active
        db_session.commit()
        status = "attivo" if user.is_active else "disabilitato"
        print(f"[AUTH] Utente {user.username} ora è {status}")
        return True
    except SQLAlchemyError as e:
        print(f"[AUTH] Errore durante il cambio di stato: {e}")
        db_session.rollback()
        return False


def set_user_role(user: User, role: str) -> bool:
    """Set user role (admin/user/viewer)."""
    try:
        user.set_role(role)
        db_session.commit()
        print(f"[AUTH] Ruolo aggiornato per {user.username}: {user.get_role()}")
        return True
    except SQLAlchemyError as e:
        print(f"[AUTH] Errore durante l'aggiornamento del ruolo: {e}")
        db_session.rollback()
        return False


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
            ip_address = (
                request_obj.headers.get('X-Real-IP')
                or request_obj.headers.get('X-Forwarded-For', '').split(',')[0].strip()
                or request_obj.remote_addr
            )
            path = request_obj.path
            method = request_obj.method
            user_agent = request_obj.headers.get('User-Agent')
        except Exception:
            pass
    try:
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
        print(f"[AUTH] Errore durante audit log: {e}")
        db_session.rollback()


def get_audit_logs(limit: int = 100):
    """Return recent audit logs."""
    if not db_session:
        return []
    try:
        return (db_session.query(AuditLog)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .all())
    except SQLAlchemyError:
        return []


def _ensure_schema(engine):
    """Ensure schema migrations for auth database."""
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        if 'users' in tables:
            columns = {col['name'] for col in inspector.get_columns('users')}
            if 'role' not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))
                    conn.execute(text("UPDATE users SET role='admin' WHERE is_admin=1"))
                    conn.execute(text("UPDATE users SET role='user' WHERE role IS NULL OR role=''"))
    except SQLAlchemyError as e:
        print(f"[AUTH] Errore durante migrazione schema: {e}")
