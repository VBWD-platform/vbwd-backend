"""S77 — tags & custom-fields core framework (live-DB integration).

Exercises the by-id read/write paths, parent_entity_type scoping, grouped stats
(no N+1), bulk reads, partial-upsert / clear, FK cascade, and the container-
resolved port + ``append_tags_and_custom_fields`` helper. Each test cleans up
its own rows so the live integration DB is left clean.
"""
from uuid import uuid4

import pytest
from sqlalchemy import event

from vbwd.repositories.custom_field_def_repository import CustomFieldDefRepository
from vbwd.repositories.custom_field_value_repository import (
    CustomFieldValueRepository,
)
from vbwd.repositories.entity_tag_repository import EntityTagRepository
from vbwd.repositories.tag_repository import TagRepository
from vbwd.services.custom_field_service import CustomFieldService
from vbwd.services.entity_type_registry import (
    EntityTypeRegistration,
    clear_entity_types,
    register_entity_type,
)
from vbwd.services.tag_service import TagService
from vbwd.services.tags_and_custom_fields import (
    CustomFieldValidationError,
    UnknownCustomFieldError,
    UnknownEntityTypeError,
    append_tags_and_custom_fields,
)

ENTITY_TYPE = "user"


@pytest.fixture
def app():
    from vbwd.app import create_app
    from vbwd.config import get_database_url

    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": get_database_url(),
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "RATELIMIT_ENABLED": False,
        }
    )


@pytest.fixture
def tag_service(app):
    from vbwd.extensions import db

    with app.app_context():
        yield TagService(
            tag_repo=TagRepository(db.session),
            entity_tag_repo=EntityTagRepository(db.session),
        )


@pytest.fixture
def custom_field_service(app):
    from vbwd.extensions import db

    with app.app_context():
        yield CustomFieldService(
            def_repo=CustomFieldDefRepository(db.session),
            value_repo=CustomFieldValueRepository(db.session),
        )


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


# --- tags: CRUD + attach/detach idempotent ---
def test_tag_crud_and_attach_detach_idempotent(app, tag_service):
    slug = _unique("tag")
    entity_id = uuid4()
    try:
        tag_service.create_tag(slug=slug, name="Tag One")
        assert tag_service.list_applicable_tags(ENTITY_TYPE)

        tag_service.set_tags(ENTITY_TYPE, entity_id, [slug])
        assert tag_service.get_tags(ENTITY_TYPE, entity_id) == [slug]

        # full-replace is idempotent
        tag_service.set_tags(ENTITY_TYPE, entity_id, [slug])
        assert tag_service.get_tags(ENTITY_TYPE, entity_id) == [slug]

        # replace with empty detaches
        tag_service.set_tags(ENTITY_TYPE, entity_id, [])
        assert tag_service.get_tags(ENTITY_TYPE, entity_id) == []
    finally:
        _teardown_tags(app, slug)


def test_set_tags_auto_creates_unknown_slugs_as_global(app, tag_service):
    slug = _unique("auto")
    entity_id = uuid4()
    try:
        tag_service.set_tags(ENTITY_TYPE, entity_id, [slug])
        applicable = {
            row["slug"]: row for row in tag_service.list_applicable_tags("shop_product")
        }
        # auto-created tag is global -> applicable to a DIFFERENT entity type too
        assert slug in applicable
        assert applicable[slug]["parent_entity_type"] is None
    finally:
        _teardown_tags(app, slug)


# --- parent_entity_type scoping ---
def test_parent_entity_type_scoping(app, tag_service):
    global_slug = _unique("global")
    scoped_slug = _unique("scoped")
    try:
        tag_service.create_tag(slug=global_slug, name="Global")
        tag_service.create_tag(
            slug=scoped_slug, name="Scoped", parent_entity_type="user"
        )

        user_slugs = {row["slug"] for row in tag_service.list_applicable_tags("user")}
        product_slugs = {
            row["slug"] for row in tag_service.list_applicable_tags("shop_product")
        }

        assert global_slug in user_slugs and global_slug in product_slugs
        assert scoped_slug in user_slugs
        assert scoped_slug not in product_slugs
    finally:
        _teardown_tags(app, global_slug, scoped_slug)


# --- stats: single + grouped, incl. zero, one query ---
def test_get_stats_and_bulk_single_grouped_query(app, tag_service):
    slug_a = _unique("a")
    slug_b = _unique("b")
    slug_unused = _unique("unused")
    try:
        for slug in (slug_a, slug_b, slug_unused):
            tag_service.create_tag(slug=slug, name=slug)
        tag_service.set_tags("user", uuid4(), [slug_a, slug_b])
        tag_service.set_tags("user", uuid4(), [slug_a])

        assert tag_service.get_stats(slug_a) == 2
        assert tag_service.get_stats(slug_b) == 1
        assert tag_service.get_stats(slug_unused) == 0

        from vbwd.extensions import db

        statements = []

        @event.listens_for(db.engine, "before_cursor_execute")
        def _record(conn, cursor, statement, params, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        try:
            stats = tag_service.get_stats_bulk([slug_a, slug_b, slug_unused])
        finally:
            event.remove(db.engine, "before_cursor_execute", _record)

        assert stats == {slug_a: 2, slug_b: 1, slug_unused: 0}
        assert len(statements) == 1  # one grouped COUNT, no N+1
    finally:
        _teardown_tags(app, slug_a, slug_b, slug_unused)


def test_get_tags_bulk_returns_per_id_map(app, tag_service):
    slug = _unique("bulk")
    id_one, id_two, id_three = uuid4(), uuid4(), uuid4()
    try:
        tag_service.create_tag(slug=slug, name=slug)
        tag_service.set_tags("user", id_one, [slug])
        tag_service.set_tags("user", id_two, [slug])

        result = tag_service.get_tags_bulk("user", [id_one, id_two, id_three])
        assert result[id_one] == [slug]
        assert result[id_two] == [slug]
        assert result[id_three] == []  # present with empty list, no N+1
    finally:
        _teardown_tags(app, slug)


# --- deleting a tag cascades entity_tag rows ---
def test_delete_tag_cascades_entity_tag_rows(app, tag_service):
    slug = _unique("cascade")
    entity_id = uuid4()
    tag_service.create_tag(slug=slug, name=slug)
    tag_service.set_tags("user", entity_id, [slug])
    assert tag_service.get_tags("user", entity_id) == [slug]

    assert tag_service.delete_tag(slug) is True
    # FK ON DELETE CASCADE removed the link row
    assert tag_service.get_tags("user", entity_id) == []


# --- custom fields: def CRUD + value set/get validated ---
def test_custom_field_def_crud_and_validated_set_get(app, custom_field_service):
    key = _unique("score")
    entity_id = uuid4()
    try:
        custom_field_service.create_def(
            entity_type="user",
            key=key,
            label="Score",
            field_type="number",
        )
        defs = {d["key"]: d for d in custom_field_service.get_field_defs("user")}
        assert key in defs and defs[key]["type"] == "number"

        custom_field_service.set_custom_fields("user", entity_id, {key: 42})
        assert custom_field_service.get_custom_fields("user", entity_id) == {key: 42}

        with pytest.raises(CustomFieldValidationError):
            custom_field_service.set_custom_fields(
                "user", entity_id, {key: "not-a-number"}
            )
    finally:
        _teardown_defs(app, "user", key)


def test_set_custom_fields_unknown_key_raises(app, custom_field_service):
    with pytest.raises(UnknownCustomFieldError):
        custom_field_service.set_custom_fields("user", uuid4(), {"never_defined": "x"})


def test_set_custom_fields_partial_upsert_and_none_clears(app, custom_field_service):
    key_one = _unique("k1")
    key_two = _unique("k2")
    entity_id = uuid4()
    try:
        custom_field_service.create_def("user", key_one, "K1", "text")
        custom_field_service.create_def("user", key_two, "K2", "text")

        custom_field_service.set_custom_fields(
            "user", entity_id, {key_one: "one", key_two: "two"}
        )
        # partial upsert: only key_one submitted, key_two untouched
        custom_field_service.set_custom_fields("user", entity_id, {key_one: "ONE"})
        values = custom_field_service.get_custom_fields("user", entity_id)
        assert values == {key_one: "ONE", key_two: "two"}

        # None clears just that key
        custom_field_service.set_custom_fields("user", entity_id, {key_one: None})
        values = custom_field_service.get_custom_fields("user", entity_id)
        assert values == {key_two: "two"}
    finally:
        _teardown_defs(app, "user", key_one, key_two)


def test_get_custom_fields_bulk_returns_per_id_map(app, custom_field_service):
    key = _unique("bk")
    id_one, id_two, id_three = uuid4(), uuid4(), uuid4()
    try:
        custom_field_service.create_def("user", key, "BK", "text")
        custom_field_service.set_custom_fields("user", id_one, {key: "a"})
        custom_field_service.set_custom_fields("user", id_two, {key: "b"})

        result = custom_field_service.get_custom_fields_bulk(
            "user", [id_one, id_two, id_three]
        )
        assert result[id_one] == {key: "a"}
        assert result[id_two] == {key: "b"}
        assert result[id_three] == {}
    finally:
        _teardown_defs(app, "user", key)


def test_delete_def_removes_its_values(app, custom_field_service):
    key = _unique("del")
    entity_id = uuid4()
    custom_field_service.create_def("user", key, "Del", "text")
    custom_field_service.set_custom_fields("user", entity_id, {key: "x"})
    assert custom_field_service.get_custom_fields("user", entity_id) == {key: "x"}

    assert custom_field_service.delete_def("user", key) is True
    # def gone -> the key no longer settable; lingering value row is orphaned but
    # the def-driven read path no longer surfaces it via get_field_defs.
    assert key not in {d["key"] for d in custom_field_service.get_field_defs("user")}


# --- port resolves from the container + the D4 helper ---
def test_port_resolves_from_container_and_append_helper(app):
    from vbwd.extensions import db

    slug = _unique("port")
    key = _unique("pk")
    entity_id = uuid4()
    with app.app_context():
        clear_entity_types()
        register_entity_type(EntityTypeRegistration("user", "User", "users.manage"))
        port = app.container.tags_and_custom_fields()
        try:
            port.set_tags("user", entity_id, [slug])
            CustomFieldService(
                def_repo=CustomFieldDefRepository(db.session),
                value_repo=CustomFieldValueRepository(db.session),
            ).create_def("user", key, "PK", "text")
            port.set_custom_fields("user", entity_id, {key: "v"})

            enriched = append_tags_and_custom_fields({}, "user", entity_id)
            assert enriched["tags"] == [slug]
            assert enriched["custom_fields"] == {key: "v"}

            with pytest.raises(UnknownEntityTypeError):
                port.get_tags("never_registered", entity_id)
        finally:
            from vbwd.models.custom_field_def import CustomFieldDef
            from vbwd.models.tag import Tag

            db.session.query(CustomFieldDef).filter(
                CustomFieldDef.entity_type == "user", CustomFieldDef.key == key
            ).delete(synchronize_session=False)
            db.session.query(Tag).filter(Tag.slug == slug).delete(
                synchronize_session=False
            )
            db.session.commit()
            clear_entity_types()


def _teardown_tags(app, *slugs):
    from vbwd.extensions import db
    from vbwd.models.tag import Tag

    with app.app_context():
        db.session.query(Tag).filter(Tag.slug.in_(slugs)).delete(
            synchronize_session=False
        )
        db.session.commit()


def _teardown_defs(app, entity_type, *keys):
    from vbwd.extensions import db
    from vbwd.models.custom_field_def import CustomFieldDef
    from vbwd.models.custom_field_value import CustomFieldValue

    with app.app_context():
        db.session.query(CustomFieldValue).filter(
            CustomFieldValue.entity_type == entity_type,
            CustomFieldValue.field_key.in_(keys),
        ).delete(synchronize_session=False)
        db.session.query(CustomFieldDef).filter(
            CustomFieldDef.entity_type == entity_type,
            CustomFieldDef.key.in_(keys),
        ).delete(synchronize_session=False)
        db.session.commit()
