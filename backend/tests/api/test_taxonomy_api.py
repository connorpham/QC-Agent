from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from tests.factories import make_session_token, make_user

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def test_taxonomy_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/taxonomy")).status_code == 401


async def test_taxonomy_lists_folders_types_and_other(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings, account_type="customer", email="c@client.com")
    c = await make_client(await make_session_token(db, settings, user))
    response = await c.get("/api/v1/taxonomy")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert [f["dir"] for f in body["folders"]][:2] == ["01-overview", "02-requirements"]
    requirements = body["folders"][1]
    assert requirements["doc_types"][1] == {
        "key": "srs",
        "id": "srs",
        "title": "Software Requirements Specification",
        "required": True,
        "normalize": True,
        "multi": False,
    }
    assert requirements["doc_types"][-1]["key"] == "requirements/other"
    assert requirements["doc_types"][-1]["required"] is False
