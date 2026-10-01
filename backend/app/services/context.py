from dataclasses import dataclass

from app.db.models import AuthSession, User


@dataclass
class SessionContext:
    auth_session: AuthSession
    user: User
