"""DB-backed tests for ``UserGroupService`` + ``DefaultUserGroupMembership`` (S73).

Mirrors ``test_core_exchangers`` (live test session via the ``app`` fixture):
CRUD + slug uniqueness + parent_group-must-exist-or-null + bulk delete; membership
add/remove/set idempotent and slug-keyed; deleting a group cascades its rel rows.
"""
from uuid import uuid4

import pytest

from vbwd.extensions import db
from vbwd.models.user import User
from vbwd.models.user_group import user_group_rel
from vbwd.services.user_group_membership import DefaultUserGroupMembership
from vbwd.services.user_group_service import (
    UserGroupService,
    UserGroupValidationError,
)


@pytest.fixture
def session(app):
    with app.app_context():
        yield db.session
        db.session.rollback()


@pytest.fixture
def service(session):
    return UserGroupService(session)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _user(session) -> User:
    user = User(email=f"s73-{uuid4().hex}@example.com", password_hash="x")
    session.add(user)
    session.flush()
    return user


class TestUserGroupCrud:
    def test_create_and_get_by_slug(self, service):
        slug = _unique("vip")
        group = service.create_group(slug=slug, name="VIP", lang="en")
        assert group.slug == slug
        fetched = service.get_by_slug(slug)
        assert fetched is not None and fetched.name == "VIP"

    def test_slug_must_be_unique(self, service):
        slug = _unique("dup")
        service.create_group(slug=slug, name="First")
        with pytest.raises(UserGroupValidationError):
            service.create_group(slug=slug, name="Second")

    def test_slug_is_required(self, service):
        with pytest.raises(UserGroupValidationError):
            service.create_group(slug="", name="No slug")

    def test_parent_group_must_exist(self, service):
        with pytest.raises(UserGroupValidationError):
            service.create_group(
                slug=_unique("child"), name="Child", parent_group="missing-parent"
            )

    def test_parent_group_may_be_null(self, service):
        group = service.create_group(slug=_unique("root"), name="Root")
        assert group.parent_group is None

    def test_parent_group_references_existing(self, service):
        parent_slug = _unique("parent")
        service.create_group(slug=parent_slug, name="Parent")
        child = service.create_group(
            slug=_unique("child"), name="Child", parent_group=parent_slug
        )
        assert child.parent_group == parent_slug

    def test_update_group(self, service):
        group = service.create_group(slug=_unique("ed"), name="Old")
        updated = service.update_group(group.id, {"name": "New", "lang": "de"})
        assert updated.name == "New"
        assert updated.lang == "de"

    def test_delete_group(self, service):
        group = service.create_group(slug=_unique("del"), name="Gone")
        assert service.delete_group(group.id) is True
        assert service.get_by_id(group.id) is None

    def test_bulk_delete(self, service):
        groups = [
            service.create_group(slug=_unique("bulk"), name=f"B{i}") for i in range(3)
        ]
        deleted = service.bulk_delete([str(g.id) for g in groups])
        assert deleted == 3
        for group in groups:
            assert service.get_by_id(group.id) is None


class TestMembership:
    def test_add_remove_set_idempotent_and_slug_keyed(self, session, service):
        membership = DefaultUserGroupMembership(session)
        user = _user(session)
        slug_a = _unique("ma")
        slug_b = _unique("mb")
        service.create_group(slug=slug_a, name="A")
        service.create_group(slug=slug_b, name="B")

        membership.add(user.id, slug_a)
        membership.add(user.id, slug_a)  # idempotent
        assert membership.list_user_group_slugs(user.id) == {slug_a}

        membership.set_user_groups(user.id, [slug_b])
        assert membership.list_user_group_slugs(user.id) == {slug_b}

        membership.remove(user.id, slug_b)
        membership.remove(user.id, slug_b)  # idempotent
        assert membership.list_user_group_slugs(user.id) == set()

    def test_add_unknown_slug_skipped(self, session):
        membership = DefaultUserGroupMembership(session)
        user = _user(session)
        membership.add(user.id, "no-such-group")
        assert membership.list_user_group_slugs(user.id) == set()

    def test_delete_group_cascades_rel_rows(self, session, service):
        membership = DefaultUserGroupMembership(session)
        user = _user(session)
        slug = _unique("casc")
        group = service.create_group(slug=slug, name="Cascade")
        membership.add(user.id, slug)
        session.flush()
        assert membership.list_user_group_slugs(user.id) == {slug}

        service.delete_group(group.id)

        remaining = session.execute(
            user_group_rel.select().where(user_group_rel.c.group_slug == slug)
        ).all()
        assert remaining == []
        assert membership.list_user_group_slugs(user.id) == set()
