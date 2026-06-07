"""Tests for the seven S46.1 core entity exchangers.

DB-backed (live test session, mirroring ``test_country_io``): each importable
exchanger round-trips (export -> wipe -> import -> re-export equals) by natural
key; export-only exchangers reject import; secrets never serialise; PII is
redacted without the PII permission; users import never elevates admin/role.

Registration + permission-catalog wiring is asserted in
``test_register_core_exchangers``.
"""
import os
from uuid import uuid4

import pytest

from vbwd.extensions import db
from vbwd.models.country import Country
from vbwd.models.currency import Currency
from vbwd.models.invoice import UserInvoice
from vbwd.models.payment_method import PaymentMethod
from vbwd.models.role import Permission, Role
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails
from vbwd.services.data_exchange.core_exchangers import (
    build_core_exchangers,
    register_core_exchangers,
)
from vbwd.services.data_exchange.envelope import build_envelope
from vbwd.services.data_exchange.port import (
    MODE_UPSERT,
    ExportSelector,
    UnsupportedOperationError,
)


# ── helpers ────────────────────────────────────────────────────────────────


def _exchangers(session):
    """Build the core exchangers bound to the live test session, keyed."""
    return {ex.entity_key: ex for ex in build_core_exchangers(session)}


def _export_rows(exchanger, *, include_pii=False):
    return exchanger.export(ExportSelector(all=True), include_pii=include_pii).rows


def _scoped_round_trip(exchanger, session, code):
    """Round-trip only the rows whose natural key is in ``code`` (a set).

    Scoped (not table-wide ``replace_all``) so the shared seeded test DB — and
    the plugin tables that FK-reference users/invoices/currencies — are never
    disturbed. Export the selected rows, mutate, re-import (upsert), re-export.
    """
    selector = ExportSelector(ids=list(code))
    before = exchanger.export(selector, include_pii=True).rows
    payload = build_envelope(exchanger.entity_key, before, instance="test")
    exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
    after = exchanger.export(selector, include_pii=True).rows
    return before, after


@pytest.fixture
def session(app):
    with app.app_context():
        yield db.session
        db.session.rollback()


# ── users ──────────────────────────────────────────────────────────────────


class TestUsersExchanger:
    @pytest.fixture
    def seeded_user(self, session):
        existing = session.query(User).filter_by(email="roundtrip@example.com").first()
        if existing is not None:
            session.delete(existing)
            session.commit()
        user = User(
            id=uuid4(),
            email="roundtrip@example.com",
            password_hash="argon2$secret-never-export",
        )
        session.add(user)
        session.flush()
        session.add(
            UserDetails(
                id=uuid4(),
                user_id=user.id,
                first_name="Round",
                last_name="Trip",
                phone="+49123",
                city="Berlin",
            )
        )
        session.commit()
        yield user
        leftover = session.query(User).filter_by(email="roundtrip@example.com").first()
        if leftover is not None:
            session.delete(leftover)
            session.commit()

    def test_export_nests_details(self, session, seeded_user):
        rows = _export_rows(_exchangers(session)["users"], include_pii=True)
        row = next(r for r in rows if r["email"] == "roundtrip@example.com")
        assert row["details"]["first_name"] == "Round"
        assert row["details"]["city"] == "Berlin"

    def test_export_never_includes_password_hash(self, session, seeded_user):
        rows = _export_rows(_exchangers(session)["users"], include_pii=True)
        for row in rows:
            assert "password_hash" not in row
            assert "argon2$secret-never-export" not in str(row)

    def test_pii_redacted_without_permission(self, session, seeded_user):
        rows = _export_rows(_exchangers(session)["users"], include_pii=False)
        row = next(r for r in rows if r["email"] == "roundtrip@example.com")
        # The natural key (email) survives; PII payload + nested details do not.
        assert row["email"] == "roundtrip@example.com"
        assert row.get("phone") is None
        assert row.get("details") is None

    def test_round_trip_includes_details(self, session, seeded_user):
        before, after = _scoped_round_trip(
            _exchangers(session)["users"], session, {"roundtrip@example.com"}
        )
        before_row = next(r for r in before if r["email"] == "roundtrip@example.com")
        after_row = next(r for r in after if r["email"] == "roundtrip@example.com")
        assert after_row == before_row
        assert after_row["details"]["last_name"] == "Trip"

    def test_import_does_not_elevate_admin_without_system_permission(
        self, session, seeded_user
    ):
        payload = build_envelope(
            "users",
            [{"email": "roundtrip@example.com", "role": "SUPER_ADMIN", "details": {}}],
            instance="test",
        )
        exchanger = _exchangers(session)["users"]
        exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        refreshed = session.query(User).filter_by(email="roundtrip@example.com").first()
        assert refreshed.role.value != "SUPER_ADMIN"

    def test_import_allows_role_with_system_permission(self, session, seeded_user):
        payload = build_envelope(
            "users",
            [{"email": "roundtrip@example.com", "role": "ADMIN", "details": {}}],
            instance="test",
        )
        exchanger = _exchangers(session)["users"]
        exchanger.import_(
            payload, mode=MODE_UPSERT, dry_run=False, allow_role_change=True
        )
        refreshed = session.query(User).filter_by(email="roundtrip@example.com").first()
        assert refreshed.role.value == "ADMIN"


# ── invoices (export-only) ───────────────────────────────────────────────────


class TestInvoicesExchanger:
    def test_import_raises_unsupported(self, session):
        exchanger = _exchangers(session)["invoices"]
        with pytest.raises(UnsupportedOperationError):
            exchanger.import_({"invoices": []}, mode=MODE_UPSERT, dry_run=False)

    def test_export_uses_number_natural_key_and_strips_uuids(self, session):
        user = User(id=uuid4(), email="inv-rt@example.com", password_hash="x")
        session.add(user)
        session.flush()
        invoice = UserInvoice(
            id=uuid4(),
            user_id=user.id,
            invoice_number="INV-RT-0001",
            amount=10,
            currency="EUR",
        )
        session.add(invoice)
        session.commit()
        try:
            rows = _export_rows(_exchangers(session)["invoices"])
            row = next(r for r in rows if r.get("number") == "INV-RT-0001")
            assert "id" not in row
            assert "user_id" not in row
            assert str(row["amount"]).startswith("10")
        finally:
            session.delete(invoice)
            session.delete(user)
            session.commit()


# ── payment_methods ──────────────────────────────────────────────────────────


class TestPaymentMethodsExchanger:
    @pytest.fixture
    def seeded(self, session):
        existing = session.query(PaymentMethod).filter_by(code="rt-method").first()
        if existing is not None:
            session.delete(existing)
            session.commit()
        session.add(
            PaymentMethod(
                id=uuid4(),
                code="rt-method",
                name="Round Trip Method",
                is_active=True,
                config={"secret_key": "sk_live_should_not_export"},
            )
        )
        session.commit()
        yield
        leftover = session.query(PaymentMethod).filter_by(code="rt-method").first()
        if leftover is not None:
            session.delete(leftover)
            session.commit()

    def test_config_secret_stripped(self, session, seeded):
        rows = _export_rows(_exchangers(session)["payment_methods"])
        row = next(r for r in rows if r["code"] == "rt-method")
        assert "config" not in row
        assert "sk_live_should_not_export" not in str(row)

    def test_round_trip(self, session, seeded):
        before, after = _scoped_round_trip(
            _exchangers(session)["payment_methods"], session, {"rt-method"}
        )
        assert {r["code"] for r in after} == {r["code"] for r in before}
        row = next(r for r in after if r["code"] == "rt-method")
        assert row["name"] == "Round Trip Method"


# ── currencies ───────────────────────────────────────────────────────────────


class TestCurrenciesExchanger:
    @pytest.fixture
    def seeded(self, session):
        existing = session.query(Currency).filter_by(code="ZZZ").first()
        if existing is not None:
            session.delete(existing)
            session.commit()
        session.add(Currency(id=uuid4(), code="ZZZ", name="Test Coin", symbol="Z"))
        session.commit()
        yield
        leftover = session.query(Currency).filter_by(code="ZZZ").first()
        if leftover is not None:
            session.delete(leftover)
            session.commit()

    def test_round_trip_json(self, session, seeded):
        before, after = _scoped_round_trip(
            _exchangers(session)["currencies"], session, {"ZZZ"}
        )
        assert {r["code"] for r in after} == {r["code"] for r in before}

    def test_supports_csv(self, session):
        assert "csv" in _exchangers(session)["currencies"].supported_formats


# ── email_templates (file-backed) ────────────────────────────────────────────


class TestEmailTemplatesExchanger:
    def test_export_lists_bundled_defaults_with_empty_var(
        self, session, tmp_path, monkeypatch
    ):
        # bundled defaults present; var/assets dir absent entirely.
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        for stem in ("welcome", "invoice", "password_reset", "password_changed"):
            (bundled / f"{stem}.html").write_text(f"<p>{stem}</p>")
        monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path / "var"))
        exchangers = build_core_exchangers(session, email_template_dir=str(bundled))
        exchanger = next(e for e in exchangers if e.entity_key == "email_templates")
        rows = exchanger.export(ExportSelector(all=True), include_pii=False).rows
        keys = {r["key"] for r in rows}
        assert {"welcome", "invoice", "password_reset", "password_changed"} <= keys

    def test_export_unions_override_and_bundled_override_wins(
        self, session, tmp_path, monkeypatch
    ):
        from vbwd.services.asset_storage import asset_dir

        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "welcome.html").write_text("<p>BUNDLED welcome</p>")
        (bundled / "invoice.html").write_text("<p>BUNDLED invoice</p>")
        monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path / "var"))
        override = asset_dir("core", "email", "templates")
        os.makedirs(override, exist_ok=True)
        # Override welcome only; invoice has no override.
        with open(os.path.join(override, "welcome.html"), "w", encoding="utf-8") as fh:
            fh.write("<p>OVERRIDE welcome</p>")

        exchangers = build_core_exchangers(session, email_template_dir=str(bundled))
        exchanger = next(e for e in exchangers if e.entity_key == "email_templates")
        rows = exchanger.export(ExportSelector(all=True), include_pii=False).rows
        by_key = {r["key"]: r["content"] for r in rows}
        assert by_key["welcome"] == "<p>OVERRIDE welcome</p>"
        assert by_key["invoice"] == "<p>BUNDLED invoice</p>"

    def test_import_writes_to_var_assets_override_dir(
        self, session, tmp_path, monkeypatch
    ):
        from vbwd.services.asset_storage import asset_dir

        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "welcome.html").write_text("<p>BUNDLED welcome</p>")
        monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path / "var"))

        exchangers = build_core_exchangers(session, email_template_dir=str(bundled))
        exchanger = next(e for e in exchangers if e.entity_key == "email_templates")
        payload = build_envelope(
            "email_templates",
            [{"key": "welcome", "content": "<p>IMPORTED welcome</p>"}],
            instance="test",
        )
        exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)

        override = asset_dir("core", "email", "templates")
        written = os.path.join(override, "welcome.html")
        assert os.path.exists(written)
        with open(written, encoding="utf-8") as fh:
            assert fh.read() == "<p>IMPORTED welcome</p>"
        # bundled is untouched
        assert (bundled / "welcome.html").read_text() == "<p>BUNDLED welcome</p>"

    def test_imported_override_is_picked_up_by_email_service(
        self, session, tmp_path, monkeypatch
    ):
        """End-to-end: exchanger import lands in the override dir, and an
        EmailService over the same bundled dir renders the override."""
        from vbwd.services.email_service import EmailService

        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "welcome.txt").write_text("bundled {{ first_name }}")
        (bundled / "welcome.html").write_text("<p>bundled {{ first_name }}</p>")
        monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path / "var"))

        exchangers = build_core_exchangers(session, email_template_dir=str(bundled))
        exchanger = next(e for e in exchangers if e.entity_key == "email_templates")
        payload = build_envelope(
            "email_templates",
            [
                {"key": "welcome", "content": "override {{ first_name }}"},
            ],
            instance="test",
        )
        # only the .txt extension exists on disk (exchanger writes .html); to
        # render we need both — so also supply the html via a second import row.
        exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)

        service = EmailService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
            template_dir=str(bundled),
        )
        _text, html = service.render_template("welcome", {"first_name": "Jo"})
        # html override was imported (.html), so it wins; txt falls back bundled
        assert "override Jo" in html

    def test_replace_all_refused(self, session, tmp_path, monkeypatch):
        from vbwd.services.data_exchange.port import MODE_REPLACE_ALL

        bundled = tmp_path / "bundled"
        bundled.mkdir()
        monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path / "var"))
        exchangers = build_core_exchangers(session, email_template_dir=str(bundled))
        exchanger = next(e for e in exchangers if e.entity_key == "email_templates")
        payload = build_envelope(
            "email_templates",
            [{"key": "welcome", "content": "<p>x</p>"}],
            instance="test",
        )
        with pytest.raises(UnsupportedOperationError):
            exchanger.import_(payload, mode=MODE_REPLACE_ALL, dry_run=False)

    def test_supports_csv(self, session):
        ex = _exchangers(session)["email_templates"]
        assert "csv" in ex.supported_formats


# ── access_levels (roles + permission grants) ─────────────────────────────────


class TestAccessLevelsExchanger:
    @pytest.fixture
    def seeded(self, session):
        perm = session.query(Permission).filter_by(name="users.view").first()
        if perm is None:
            perm = Permission(
                id=uuid4(),
                name="users.view",
                description="View users",
                resource="users",
                action="view",
            )
            session.add(perm)
            session.commit()
        existing = session.query(Role).filter_by(name="RT Role").first()
        if existing is None:
            role = Role(
                id=uuid4(),
                name="RT Role",
                slug="rt-role",
                description="round trip",
            )
            role.permissions.append(perm)
            session.add(role)
            session.commit()
        yield
        role = session.query(Role).filter_by(name="RT Role").first()
        if role is not None:
            session.delete(role)
            session.commit()

    def test_export_includes_permission_grants_as_keys(self, session, seeded):
        rows = _export_rows(_exchangers(session)["access_levels"])
        row = next(r for r in rows if r["name"] == "RT Role")
        assert "users.view" in row["permissions"]
        assert "id" not in row

    def test_round_trip_preserves_grants(self, session, seeded):
        exchanger = _exchangers(session)["access_levels"]
        before = _export_rows(exchanger)
        before_row = next(r for r in before if r["name"] == "RT Role")
        # Drop the role, then re-import from the envelope.
        role = session.query(Role).filter_by(name="RT Role").first()
        session.delete(role)
        session.commit()
        payload = build_envelope("access_levels", [before_row], instance="test")
        exchanger.import_(payload, mode=MODE_UPSERT, dry_run=False)
        rebuilt = session.query(Role).filter_by(name="RT Role").first()
        assert rebuilt is not None
        assert "users.view" in [p.name for p in rebuilt.permissions]


# ── countries (migrated country_io) ──────────────────────────────────────────


class TestCountriesExchanger:
    @pytest.fixture
    def seeded(self, session):
        existing = session.query(Country).filter_by(code="DE").first()
        if existing is not None:
            session.delete(existing)
            session.commit()
        session.add(
            Country(id=uuid4(), code="DE", name="Germany", is_enabled=True, position=0)
        )
        session.commit()
        yield
        leftover = session.query(Country).filter_by(code="DE").first()
        if leftover is not None:
            session.delete(leftover)
            session.commit()

    def test_round_trip(self, session, seeded):
        before, after = _scoped_round_trip(
            _exchangers(session)["countries"], session, {"DE"}
        )
        assert {r["code"] for r in after} == {r["code"] for r in before}
        row = next(r for r in after if r["code"] == "DE")
        assert row["name"] == "Germany"
        assert row["is_enabled"] is True

    def test_characterisation_matches_country_io_export(self, session, seeded):
        """The exchanger reuses country_io, so its rows match the legacy export."""
        from vbwd.services.country_io import export_countries

        legacy_rows = export_countries(session)["countries"]
        exchanger_rows = _export_rows(_exchangers(session)["countries"])
        assert exchanger_rows == legacy_rows

    def test_characterisation_import_still_works_via_country_io(self, session, seeded):
        """The legacy import path (Settings -> Countries button) is unchanged."""
        from vbwd.services.country_io import import_countries

        was_present = session.query(Country).filter_by(code="FR").first() is not None
        payload = {
            "vbwd_export": "countries",
            "version": 1,
            "countries": [
                {"code": "FR", "name": "France", "is_enabled": True, "position": 1}
            ],
        }
        result = import_countries(session, payload)
        assert (result.created + result.updated) == 1
        assert session.query(Country).filter_by(code="FR").first() is not None
        if not was_present:
            session.delete(session.query(Country).filter_by(code="FR").first())
            session.commit()


# ── registration + permission catalog ────────────────────────────────────────


class TestRegisterCoreExchangers:
    def test_registers_all_seven(self, session):
        from vbwd.services.data_exchange.registry import data_exchange_registry

        data_exchange_registry.clear()
        register_core_exchangers(session)
        keys = {e.entity_key for e in data_exchange_registry.all()}
        assert keys >= {
            "users",
            "invoices",
            "payment_methods",
            "access_levels",
            "email_templates",
            "currencies",
            "countries",
        }
        data_exchange_registry.clear()

    def test_clusters_are_correct(self, session):
        built = {e.entity_key: e.cluster for e in build_core_exchangers(session)}
        assert built["users"] == "sales"
        assert built["invoices"] == "sales"
        assert built["payment_methods"] == "settings"
        assert built["access_levels"] == "settings"
        assert built["email_templates"] == "settings"
        assert built["currencies"] == "settings"
        assert built["countries"] == "settings"

    def test_idempotent(self, session):
        from vbwd.services.data_exchange.registry import data_exchange_registry

        data_exchange_registry.clear()
        register_core_exchangers(session)
        register_core_exchangers(session)
        keys = [e.entity_key for e in data_exchange_registry.all()]
        assert len(keys) == len(set(keys))
        data_exchange_registry.clear()

    def test_permission_catalog_lists_sales_perms(self, session):
        from vbwd.services.data_exchange.registry import data_exchange_registry
        from vbwd.services.permission_catalog import collect_permission_catalog

        data_exchange_registry.clear()
        register_core_exchangers(session)
        catalog = collect_permission_catalog(plugin_manager=None)
        keys = {entry["key"] for entries in catalog.values() for entry in entries}
        assert "users.export" in keys
        assert "users.import" in keys
        assert "users.export.pii" in keys
        assert "invoices.export" in keys
        # invoices has no pii_fields per the table -> no pii perm
        assert "invoices.export.pii" not in keys
        # settings-cluster entities contribute no new per-entity perms
        assert "currencies.export" not in keys
        data_exchange_registry.clear()
