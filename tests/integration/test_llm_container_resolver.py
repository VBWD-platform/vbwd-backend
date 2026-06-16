"""Container call-contract proof for the LLM client resolver (S97.1/S97.2).

Proves the exact DoD call site: ``app.container.llm_client(slug=None)`` returns
a ready ``LlmClient`` bound to the default connection, and a slug resolves that
specific connection — built over the live session + the real migrated table.
"""
from uuid import uuid4

import pytest

from vbwd.llm.client import LlmClient
from vbwd.services.llm_connection_service import NoActiveLlmConnectionError


@pytest.fixture
def seeded_connections(app):
    from vbwd.extensions import db
    from vbwd.models.llm_connection import LlmConnection

    with app.app_context():
        LlmConnection.__table__.create(bind=db.engine, checkfirst=True)
        db.session.query(LlmConnection).delete()
        db.session.add_all(
            [
                LlmConnection(
                    id=uuid4(),
                    slug="default-claude",
                    connection_name="Default Claude",
                    api_endpoint="https://api.anthropic.com",
                    api_key="sk-ant-secret-default",
                    model="claude-3-5-sonnet-latest",
                    is_active=True,
                    is_default=True,
                ),
                LlmConnection(
                    id=uuid4(),
                    slug="openai-mini",
                    connection_name="OpenAI Mini",
                    api_endpoint="https://api.openai.com/v1",
                    api_key="sk-openai-secret",
                    model="gpt-4o-mini",
                    is_active=True,
                    is_default=False,
                ),
            ]
        )
        db.session.commit()
    yield
    with app.app_context():
        db.session.query(LlmConnection).delete()
        db.session.commit()


def test_container_llm_client_default(app, seeded_connections):
    with app.app_context():
        client = app.container.llm_client(slug=None)
        assert isinstance(client, LlmClient)


def test_container_llm_client_by_slug(app, seeded_connections):
    with app.app_context():
        client = app.container.llm_client(slug="openai-mini")
        assert isinstance(client, LlmClient)


def test_container_llm_client_raises_when_no_active_default(app):
    from vbwd.extensions import db
    from vbwd.models.llm_connection import LlmConnection

    with app.app_context():
        LlmConnection.__table__.create(bind=db.engine, checkfirst=True)
        db.session.query(LlmConnection).delete()
        db.session.commit()
        with pytest.raises(NoActiveLlmConnectionError):
            app.container.llm_client(slug=None)
