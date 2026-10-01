import os

from cryptography.fernet import Fernet

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://qc:qc@localhost:5433/qc_agent_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-for-production")
os.environ.setdefault("SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["COOKIE_SECURE"] = "false"
