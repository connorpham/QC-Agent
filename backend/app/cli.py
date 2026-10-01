import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.emails import is_valid_email, normalize_email
from app.db.session import dispose_engine, init_engine
from app.services.users import DuplicateEmail, create_user


async def create_admin(db: AsyncSession, email: str, display_name: str) -> str:
    _, temporary = await create_user(
        db,
        email=email,
        display_name=display_name,
        account_type="internal",
        is_admin=True,
        actor_id=None,
    )
    return temporary


async def _create_admin_command(email: str, display_name: str) -> int:
    if not is_valid_email(normalize_email(email)):
        print("Enter a valid e-mail address.", file=sys.stderr)
        return 1
    maker = init_engine(get_settings().database_url)
    try:
        async with maker() as db:
            try:
                temporary = await create_admin(db, email, display_name)
            except DuplicateEmail:
                print("A user with this e-mail already exists.", file=sys.stderr)
                return 1
    finally:
        await dispose_engine()
    print(f"Administrator created. Temporary password (shown once): {temporary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qc-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="Create an internal administrator account")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return asyncio.run(_create_admin_command(args.email, args.name))
    return 2


def run() -> None:
    sys.exit(main())
