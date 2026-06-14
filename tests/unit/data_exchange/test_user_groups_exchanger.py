"""S73 data-exchange tests: the ``user_groups`` exchanger + ``users.group_slugs``.

DB-backed (live test session, mirroring ``test_core_exchangers``):

* ``user_groups`` round-trips json+csv by slug, with ``parent_group`` portable;
* the ``users`` exchanger carries ``group_slugs`` so user import/export
  round-trips memberships by slug through the core membership port.
"""
from uuid import uuid4

import pytest

from vbwd.extensions import db
from vbwd.models.user import User
from vbwd.models.user_group import UserGroup
from vbwd.services.data_exchange.core_exchangers import build_core_exchangers
from vbwd.services.data_exchange.envelope import build_envelope, rows_to_csv
from vbwd.services.data_exchange.port import MODE_UPSERT, ExportSelector
from vbwd.services.user_group_membership import DefaultUserGroupMembership


@pytest.fixture
def session(app):
    with app.app_context():
        yield db.session
        db.session.rollback()


def _exchangers(session):
    return {ex.entity_key: ex for ex in build_core_exchangers(session)}


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


class TestUserGroupsExchanger:
    def test_registered_with_settings_cluster_and_formats(self, session):
        exchanger = _exchangers(session)["user_groups"]
        assert exchanger.natural_key == "slug"
        assert exchanger.supported_formats == frozenset({"json", "csv"})

    def test_json_round_trip_preserves_parent_group(self, session):
        exchanger = _exchangers(session)["user_groups"]
        parent_slug = _unique("parent")
        child_slug = _unique("child")
        session.add(UserGroup(id=uuid4(), slug=parent_slug, name="Parent"))
        session.add(
            UserGroup(
                id=uuid4(),
                slug=child_slug,
                name="Child",
                lang="en",
                parent_group=parent_slug,
            )
        )
        session.commit()

        selector = ExportSelector(ids=[parent_slug, child_slug])
        before = exchanger.export(selector, include_pii=True).rows
        payload = build_envelope("user_groups", before, instance="test")
        exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        after = exchanger.export(selector, include_pii=True).rows

        # Order-insensitive round-trip equality (export row order is DB-defined).
        by_slug = {row["slug"]: row for row in after}
        assert {row["slug"]: row for row in before} == by_slug
        child_row = by_slug[child_slug]
        assert child_row["parent_group"] == parent_slug
        assert child_row["lang"] == "en"

    def test_csv_export_is_supported(self, session):
        exchanger = _exchangers(session)["user_groups"]
        slug = _unique("csv")
        session.add(UserGroup(id=uuid4(), slug=slug, name="CSV Group"))
        session.commit()

        rows = exchanger.export(ExportSelector(ids=[slug]), include_pii=True).rows
        csv_text = rows_to_csv(rows)
        assert "slug" in csv_text
        assert slug in csv_text


class TestUsersExchangerCarriesGroupSlugs:
    def test_export_includes_group_slugs(self, session):
        membership = DefaultUserGroupMembership(session)
        slug = _unique("vip")
        session.add(UserGroup(id=uuid4(), slug=slug, name="VIP"))
        user = User(email=f"s73-ex-{uuid4().hex}@example.com", password_hash="x")
        session.add(user)
        session.flush()
        membership.add(user.id, slug)
        session.commit()

        exchanger = _exchangers(session)["users"]
        rows = exchanger.export(ExportSelector(ids=[user.email]), include_pii=True).rows
        assert rows[0]["group_slugs"] == [slug]

    def test_import_round_trips_group_slugs(self, session):
        membership = DefaultUserGroupMembership(session)
        slug = _unique("trial")
        session.add(UserGroup(id=uuid4(), slug=slug, name="Trial"))
        user = User(email=f"s73-imp-{uuid4().hex}@example.com", password_hash="x")
        session.add(user)
        session.commit()
        assert membership.list_user_group_slugs(user.id) == set()

        exchanger = _exchangers(session)["users"]
        payload = build_envelope(
            "users",
            [{"email": user.email, "group_slugs": [slug]}],
            instance="test",
        )
        exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)

        assert membership.list_user_group_slugs(user.id) == {slug}

        # Re-import with an empty set removes the managed membership (replace-set).
        payload = build_envelope(
            "users",
            [{"email": user.email, "group_slugs": []}],
            instance="test",
        )
        exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        assert membership.list_user_group_slugs(user.id) == set()
