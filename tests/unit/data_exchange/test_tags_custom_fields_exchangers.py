"""S77 slice 2 — tags + custom_field_defs data-exchange exchangers.

DB-backed (live test session, mirroring ``test_core_exchangers``): both
exchangers round-trip by their natural key (``tags`` by ``slug``,
``custom_field_defs`` by the composite ``(entity_type, key)``), json+csv;
import is idempotent and keyed (no primary ids leak into the envelope);
re-import updates in place. They register into the core registry.
"""
from uuid import uuid4

import pytest

from vbwd.extensions import db
from vbwd.models.custom_field_def import CustomFieldDef
from vbwd.models.tag import Tag
from vbwd.services.data_exchange.core_exchangers import (
    build_core_exchangers,
    register_core_exchangers,
)
from vbwd.services.data_exchange.envelope import build_envelope, rows_to_csv
from vbwd.services.data_exchange.port import MODE_UPSERT, ExportSelector


@pytest.fixture
def session(app):
    with app.app_context():
        yield db.session
        db.session.rollback()


def _exchangers(session):
    return {ex.entity_key: ex for ex in build_core_exchangers(session)}


# ── tags (single natural key: slug) ──────────────────────────────────────────


class TestTagsExchanger:
    @pytest.fixture
    def seeded(self, session):
        slug = f"rt-tag-{uuid4().hex[:8]}"
        existing = session.query(Tag).filter_by(slug=slug).first()
        if existing is not None:
            session.delete(existing)
            session.commit()
        session.add(
            Tag(
                id=uuid4(),
                slug=slug,
                name="Round Trip Tag",
                parent_entity_type="user",
                meta_data={"hint": "blue"},
                color="#0066ff",
            )
        )
        session.commit()
        yield slug
        leftover = session.query(Tag).filter_by(slug=slug).first()
        if leftover is not None:
            session.delete(leftover)
            session.commit()

    def test_registered_with_slug_natural_key_and_csv(self, session):
        exchanger = _exchangers(session)["tags"]
        assert exchanger.natural_key == "slug"
        assert "csv" in exchanger.supported_formats
        assert "json" in exchanger.supported_formats

    def test_export_strips_uuid_and_keeps_catalog_fields(self, session, seeded):
        rows = (
            _exchangers(session)["tags"]
            .export(ExportSelector(ids=[seeded]), include_pii=False)
            .rows
        )
        row = next(r for r in rows if r["slug"] == seeded)
        assert "id" not in row
        assert set(row) == {"slug", "name", "parent_entity_type", "meta_data", "color"}
        assert row["parent_entity_type"] == "user"
        assert row["meta_data"] == {"hint": "blue"}
        assert row["color"] == "#0066ff"

    def test_round_trip_json_recreates_by_slug(self, session, seeded):
        exchanger = _exchangers(session)["tags"]
        before = exchanger.export(ExportSelector(ids=[seeded]), include_pii=True).rows
        tag = session.query(Tag).filter_by(slug=seeded).first()
        session.delete(tag)
        session.commit()
        payload = build_envelope("tags", before, instance="test")
        result = exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        assert result.errors == []
        assert result.created == 1
        rebuilt = session.query(Tag).filter_by(slug=seeded).first()
        assert rebuilt is not None
        assert rebuilt.name == "Round Trip Tag"
        assert rebuilt.parent_entity_type == "user"

    def test_import_is_idempotent_upsert_by_slug(self, session, seeded):
        exchanger = _exchangers(session)["tags"]
        before = exchanger.export(ExportSelector(ids=[seeded]), include_pii=True).rows
        payload = build_envelope("tags", before, instance="test")
        first = exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        second = exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        assert first.created == 0 and first.updated == 1
        assert second.created == 0 and second.updated == 1
        assert session.query(Tag).filter_by(slug=seeded).count() == 1

    def test_reimport_updates_in_place(self, session, seeded):
        exchanger = _exchangers(session)["tags"]
        before = exchanger.export(ExportSelector(ids=[seeded]), include_pii=True).rows
        row = next(r for r in before if r["slug"] == seeded)
        row["name"] = "Renamed Tag"
        payload = build_envelope("tags", [row], instance="test")
        exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        rebuilt = session.query(Tag).filter_by(slug=seeded).first()
        assert rebuilt.name == "Renamed Tag"

    def test_csv_columns_are_catalog_fields(self, session, seeded):
        exchanger = _exchangers(session)["tags"]
        rows = exchanger.export(ExportSelector(ids=[seeded]), include_pii=True).rows
        header = rows_to_csv(rows).splitlines()[0].split(",")
        assert set(header) == {
            "slug",
            "name",
            "parent_entity_type",
            "meta_data",
            "color",
        }


# ── custom_field_defs (composite natural key: entity_type + key) ─────────────


class TestCustomFieldDefsExchanger:
    @pytest.fixture
    def seeded(self, session):
        key = f"rt-def-{uuid4().hex[:8]}"
        existing = (
            session.query(CustomFieldDef).filter_by(entity_type="user", key=key).first()
        )
        if existing is not None:
            session.delete(existing)
            session.commit()
        session.add(
            CustomFieldDef(
                id=uuid4(),
                entity_type="user",
                key=key,
                label="Round Trip Def",
                type="select",
                options=["a", "b"],
                sort_order=5,
                is_active=True,
            )
        )
        session.commit()
        yield key
        leftover = (
            session.query(CustomFieldDef).filter_by(entity_type="user", key=key).first()
        )
        if leftover is not None:
            session.delete(leftover)
            session.commit()

    def test_registered_with_composite_natural_key_and_csv(self, session):
        exchanger = _exchangers(session)["custom_field_defs"]
        assert "csv" in exchanger.supported_formats
        assert "json" in exchanger.supported_formats

    def test_export_strips_uuid_and_keeps_def_fields(self, session, seeded):
        rows = (
            _exchangers(session)["custom_field_defs"]
            .export(ExportSelector(all=True), include_pii=False)
            .rows
        )
        row = next(r for r in rows if r["entity_type"] == "user" and r["key"] == seeded)
        assert "id" not in row
        assert set(row) == {
            "entity_type",
            "key",
            "label",
            "type",
            "options",
            "sort_order",
            "is_active",
        }
        assert row["type"] == "select"
        assert row["options"] == ["a", "b"]
        assert row["sort_order"] == 5

    def test_round_trip_json_recreates_by_composite_key(self, session, seeded):
        exchanger = _exchangers(session)["custom_field_defs"]
        before = exchanger.export(ExportSelector(all=True), include_pii=True).rows
        before_row = next(
            r for r in before if r["entity_type"] == "user" and r["key"] == seeded
        )
        definition = (
            session.query(CustomFieldDef)
            .filter_by(entity_type="user", key=seeded)
            .first()
        )
        session.delete(definition)
        session.commit()
        payload = build_envelope("custom_field_defs", [before_row], instance="test")
        result = exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        assert result.errors == []
        assert result.created == 1
        rebuilt = (
            session.query(CustomFieldDef)
            .filter_by(entity_type="user", key=seeded)
            .first()
        )
        assert rebuilt is not None
        assert rebuilt.label == "Round Trip Def"
        assert rebuilt.type == "select"
        assert rebuilt.options == ["a", "b"]

    def test_import_is_idempotent_upsert_by_composite_key(self, session, seeded):
        exchanger = _exchangers(session)["custom_field_defs"]
        before = exchanger.export(ExportSelector(all=True), include_pii=True).rows
        row = next(
            r for r in before if r["entity_type"] == "user" and r["key"] == seeded
        )
        payload = build_envelope("custom_field_defs", [row], instance="test")
        first = exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        second = exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        assert first.created == 0 and first.updated == 1
        assert second.created == 0 and second.updated == 1
        assert (
            session.query(CustomFieldDef)
            .filter_by(entity_type="user", key=seeded)
            .count()
            == 1
        )

    def test_reimport_updates_in_place(self, session, seeded):
        exchanger = _exchangers(session)["custom_field_defs"]
        before = exchanger.export(ExportSelector(all=True), include_pii=True).rows
        row = next(
            r for r in before if r["entity_type"] == "user" and r["key"] == seeded
        )
        row["label"] = "Renamed Def"
        payload = build_envelope("custom_field_defs", [row], instance="test")
        exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        rebuilt = (
            session.query(CustomFieldDef)
            .filter_by(entity_type="user", key=seeded)
            .first()
        )
        assert rebuilt.label == "Renamed Def"

    def test_missing_composite_key_is_reported(self, session):
        exchanger = _exchangers(session)["custom_field_defs"]
        payload = build_envelope(
            "custom_field_defs", [{"label": "no keys"}], instance="test"
        )
        result = exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        assert result.errors
        assert result.created == 0 and result.updated == 0


# ── registration ─────────────────────────────────────────────────────────────


def test_tags_and_defs_registered_as_core_exchangers(session):
    from vbwd.services.data_exchange.registry import data_exchange_registry

    data_exchange_registry.clear()
    register_core_exchangers(session)
    keys = {e.entity_key for e in data_exchange_registry.all()}
    assert {"tags", "custom_field_defs"} <= keys
    data_exchange_registry.clear()
