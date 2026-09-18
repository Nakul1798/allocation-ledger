import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


def _normalize_db_url(url: str) -> str:
    # Render (and some other hosts) hand out "postgres://", but SQLAlchemy 1.4+/psycopg2
    # wants "postgresql://".
    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")

    _db_url = os.environ.get("DATABASE_URL", "")
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(_db_url) or (
        "sqlite:///" + os.path.join(basedir, "instance", "app.db")
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER", os.path.join(basedir, "instance", "uploads")
    )
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB, matches the PDF-only upload fields
    ALLOWED_UPLOAD_EXTENSIONS = {"pdf"}

    # Session / cookie security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    WTF_CSRF_TIME_LIMIT = None

    # Login throttling
    MAX_LOGIN_ATTEMPTS = 5
    LOGIN_LOCKOUT_MINUTES = 15


class DevConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False


class ProdConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevConfig,
    "testing": TestConfig,
    "production": ProdConfig,
}
