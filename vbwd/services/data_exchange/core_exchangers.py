"""The core entity exchangers.

These are *core* entities (users+details, invoices, payment methods, access
levels, email templates, currencies, countries, taxes, token
bundles), so —
unlike plugin exchangers which register at plugin enable-time — they are
registered directly at app init via :func:`register_core_exchangers`. The
function is idempotent and clear-safe so the test suite can rebuild the
registry freely.

Each exchanger honours the generic :class:`EntityExchanger` contract:

* straightforward one-model entities (payment methods, currencies) subclass the
  generic :class:`BaseModelExchanger` over a thin session-backed repository;
* entities with bespoke shaping (users' nested 1:1 details + role guard,
  invoices' export-only contract, access levels' permission grants, the
  file-backed email templates, countries wrapping the legacy ``country_io``)
  implement :class:`EntityExchanger` directly — extension, not core change.

No raw SQL: all reads/writes go through the model layer + session.
"""
import os
from typing import Any, List, Optional

from vbwd.models.country import Country
from vbwd.models.currency import Currency
from vbwd.models.custom_field_def import CustomFieldDef
from vbwd.models.invoice import UserInvoice
from vbwd.models.payment_method import PaymentMethod
from vbwd.models.role import Permission, Role
from vbwd.models.tag import Tag
from vbwd.models.tax import Tax
from vbwd.models.token_bundle import TokenBundle
from vbwd.models.user import User
from vbwd.models.user_details import UserDetails
from vbwd.models.user_group import UserGroup
from vbwd.services.asset_storage import asset_dir
from vbwd.services.data_exchange.base_model_exchanger import BaseModelExchanger
from vbwd.services.data_exchange.envelope import validate_envelope
from vbwd.services.data_exchange.port import (
    CLUSTER_SALES,
    CLUSTER_SETTINGS,
    MODE_REPLACE_ALL,
    EntityExchanger,
    Envelope,
    ExportSelector,
    ImportResult,
    UnsupportedOperationError,
)
from vbwd.services.data_exchange.registry import data_exchange_registry

# Default on-disk home of the core email templates (relative to the package).
DEFAULT_EMAIL_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates", "email"
)
EMAIL_TEMPLATE_SUFFIX = ".html"


class _SessionModelRepository:
    """Minimal repository over one model satisfying the BaseModelExchanger
    contract (``find_all`` / ``find_by_natural_key`` / ``add`` / ``delete_all``).

    Core's existing repositories don't expose this exact narrow interface, so
    this adapter provides it without touching them (ISP: the exchanger depends
    only on the four methods it uses).
    """

    def __init__(self, session: Any, model_class: type, natural_key: str):
        self._session = session
        self._model_class = model_class
        self._natural_key = natural_key

    def find_all(self) -> List[Any]:
        return self._session.query(self._model_class).all()

    def find_by_natural_key(self, value: Any) -> Optional[Any]:
        column = getattr(self._model_class, self._natural_key)
        return self._session.query(self._model_class).filter(column == value).first()

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def delete_all(self) -> None:
        self._session.query(self._model_class).delete()


# ── payment_methods + currencies (generic BaseModelExchanger) ────────────────


def _build_payment_methods_exchanger(session: Any) -> BaseModelExchanger:
    return BaseModelExchanger(
        entity_key="payment_methods",
        label="Payment Methods",
        cluster=CLUSTER_SETTINGS,
        natural_key="code",
        model_class=PaymentMethod,
        repository=_SessionModelRepository(session, PaymentMethod, "code"),
        session=session,
        public_fields=[
            "code",
            "name",
            "description",
            "short_description",
            "icon",
            "plugin_id",
            "is_active",
            "is_default",
            "position",
            "fee_type",
            "fee_charged_to",
            "instructions",
        ],
        # ``config`` holds provider/credential secrets — never exported (D9).
        secret_fields=frozenset({"config"}),
        supported_formats=frozenset({"json", "csv"}),
    )


def _build_currencies_exchanger(session: Any) -> BaseModelExchanger:
    return BaseModelExchanger(
        entity_key="currencies",
        label="Currencies",
        cluster=CLUSTER_SETTINGS,
        natural_key="code",
        model_class=Currency,
        repository=_SessionModelRepository(session, Currency, "code"),
        session=session,
        public_fields=[
            "code",
            "name",
            "symbol",
            "exchange_rate",
            "decimal_places",
        ],
        supported_formats=frozenset({"json", "csv"}),
    )


# ── token_bundles (flat model keyed by name) ─────────────────────────────────


def _build_token_bundles_exchanger(session: Any) -> BaseModelExchanger:
    # TokenBundle has no code/slug, so ``name`` is the stable human identifier
    # used as the natural key for portable, idempotent upsert across instances.
    return BaseModelExchanger(
        entity_key="token_bundles",
        label="Token Bundles",
        cluster=CLUSTER_SETTINGS,
        natural_key="name",
        model_class=TokenBundle,
        repository=_SessionModelRepository(session, TokenBundle, "name"),
        session=session,
        public_fields=[
            "name",
            "description",
            "token_amount",
            "price",
            "is_active",
            "sort_order",
        ],
        supported_formats=frozenset({"json", "csv"}),
    )


# ── taxes (flat model keyed by code, ``tax_class`` a plain label) ─────────────


def _build_taxes_exchanger(session: Any) -> BaseModelExchanger:
    return BaseModelExchanger(
        entity_key="taxes",
        label="Taxes",
        cluster=CLUSTER_SETTINGS,
        natural_key="code",
        model_class=Tax,
        repository=_SessionModelRepository(session, Tax, "code"),
        session=session,
        public_fields=[
            "name",
            "code",
            "description",
            "rate",
            "country_code",
            "region_code",
            "is_active",
            "is_inclusive",
            "tax_class",
        ],
        supported_formats=frozenset({"json", "csv"}),
    )


# ── user_groups (flat model keyed by slug, parent_group portable by slug) ────


def _build_user_groups_exchanger(session: Any) -> BaseModelExchanger:
    # parent_group is itself a slug, so the envelope is instance-independent
    # without any FK resolution (D1: slug-keyed hierarchy keeps it portable).
    return BaseModelExchanger(
        entity_key="user_groups",
        label="User Groups",
        cluster=CLUSTER_SETTINGS,
        natural_key="slug",
        model_class=UserGroup,
        repository=_SessionModelRepository(session, UserGroup, "slug"),
        session=session,
        public_fields=[
            "slug",
            "name",
            "lang",
            "parent_group",
        ],
        supported_formats=frozenset({"json", "csv"}),
    )


# ── tags (S77 catalog, keyed by globally-unique slug) ────────────────────────


def _build_tags_exchanger(session: Any) -> BaseModelExchanger:
    # The single core tag catalog (S77). ``slug`` is globally unique, so the
    # generic BaseModelExchanger upserts by it; ``meta_data`` is a JSON dict
    # (CSV-encoded into one cell). No secrets/PII.
    return BaseModelExchanger(
        entity_key="tags",
        label="Tags",
        cluster=CLUSTER_SETTINGS,
        natural_key="slug",
        model_class=Tag,
        repository=_SessionModelRepository(session, Tag, "slug"),
        session=session,
        public_fields=[
            "slug",
            "name",
            "parent_entity_type",
            "meta_data",
            "color",
        ],
        supported_formats=frozenset({"json", "csv"}),
    )


# ── custom_field_defs (S77, composite natural key entity_type + key) ─────────


class CustomFieldDefsExchanger(EntityExchanger):
    """Custom-field definitions (S77), keyed by ``(entity_type, key)``.

    ``key`` is unique only *per* entity_type, so the natural key is composite —
    the generic single-key :class:`BaseModelExchanger` cannot express it. This
    exchanger therefore implements the contract directly (extension, not core
    change), mirroring :class:`AccessLevelsExchanger`. Upsert matches on the
    pair; ``options`` is a JSON list (CSV-encoded into one cell). No secrets.
    """

    entity_key = "custom_field_defs"
    label = "Custom Field Definitions"
    cluster = CLUSTER_SETTINGS
    natural_key = "key"
    supports_export = True
    supports_import = True
    supported_formats = frozenset({"json", "csv"})
    secret_fields = frozenset()
    pii_fields = frozenset()

    _FIELDS = (
        "entity_type",
        "key",
        "label",
        "type",
        "options",
        "sort_order",
        "is_active",
    )

    def __init__(self, session: Any):
        self._session = session

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        defs = self._session.query(CustomFieldDef).all()
        if selector.ids:
            wanted = {str(value) for value in selector.ids}
            defs = [
                definition
                for definition in defs
                if str(definition.id) in wanted or definition.key in wanted
            ]
        rows = [self._serialise(definition) for definition in defs]
        return Envelope(entity_key=self.entity_key, rows=rows)

    def _serialise(self, definition: CustomFieldDef) -> dict:
        return {
            field_name: getattr(definition, field_name) for field_name in self._FIELDS
        }

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        rows = validate_envelope(payload, self.entity_key)
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        try:
            for index, row in enumerate(rows):
                self._import_row(row, index, result, dry_run=dry_run)
        except Exception:
            self._session.rollback()
            raise
        if dry_run:
            self._session.rollback()
        else:
            self._session.commit()
        return result

    def _import_row(
        self, row: dict, index: int, result: ImportResult, *, dry_run: bool
    ) -> None:
        entity_type = row.get("entity_type")
        key = row.get("key")
        if not entity_type or not key:
            result.errors.append(
                {"row": index, "reason": "missing natural key '(entity_type, key)'"}
            )
            return
        existing = (
            self._session.query(CustomFieldDef)
            .filter(
                CustomFieldDef.entity_type == entity_type,
                CustomFieldDef.key == key,
            )
            .first()
        )
        if existing is not None:
            if not dry_run:
                for field_name in (
                    "label",
                    "type",
                    "options",
                    "sort_order",
                    "is_active",
                ):
                    if field_name in row:
                        setattr(existing, field_name, row[field_name])
            result.updated += 1
        else:
            if not dry_run:
                self._session.add(
                    CustomFieldDef(
                        **{
                            field_name: row[field_name]
                            for field_name in self._FIELDS
                            if field_name in row
                        }
                    )
                )
            result.created += 1


# ── users (nested 1:1 details + PII split + role guard) ──────────────────────


class UsersExchanger(EntityExchanger):
    """Users + their 1:1 ``UserDetails`` (all-PII), keyed by ``email``.

    Export nests the whole details block under ``details`` and redacts every
    PII field (incl. that block) unless ``include_pii`` is set. ``password_hash``
    and token columns are never serialised. Import upserts by email and — per
    the security model — never elevates ``role`` unless ``allow_role_change`` is
    passed (the route passes it only when the caller holds ``settings.system``).
    """

    entity_key = "users"
    label = "Users"
    cluster = CLUSTER_SALES
    natural_key = "email"
    supports_export = True
    supports_import = True
    supported_formats = frozenset({"json", "csv"})
    secret_fields = frozenset({"password_hash"})
    # The whole personal payload (incl. the nested 1:1 details) is PII; a
    # non-empty set is also what gives this exchanger its ``.export.pii`` perm.
    pii_fields = frozenset({"phone", "details"})

    _DETAILS_FIELDS = (
        "first_name",
        "last_name",
        "address_line_1",
        "address_line_2",
        "city",
        "postal_code",
        "country",
        "phone",
        "company",
        "tax_number",
        "account_type",
    )

    def __init__(self, session: Any):
        self._session = session

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        users = self._select(selector)
        rows = [self._serialise(user, include_pii=include_pii) for user in users]
        return Envelope(entity_key=self.entity_key, rows=rows)

    def _select(self, selector: ExportSelector) -> List[User]:
        query = self._session.query(User)
        if selector.ids:
            users = query.all()
            wanted = {str(value) for value in selector.ids}
            return [
                user
                for user in users
                if str(user.id) in wanted or (user.email and user.email in wanted)
            ]
        return query.all()

    def _serialise(self, user: User, *, include_pii: bool) -> dict:
        # Group membership (S73) is not PII — it round-trips by slug in both the
        # redacted and full export so user import carries memberships.
        group_slugs = self._group_slugs(user)
        row: dict = {
            "email": user.email,
            "status": user.status.value if user.status else None,
            "role": user.role.value if user.role else None,
            "has_used_trial": bool(user.has_used_trial),
            "group_slugs": group_slugs,
        }
        if not include_pii:
            return {
                "email": user.email,
                "role": row["role"],
                "group_slugs": group_slugs,
            }
        details: Optional[UserDetails] = getattr(user, "details", None)
        row["details"] = self._serialise_details(details)
        return row

    def _group_slugs(self, user: User) -> list:
        from vbwd.services.user_group_membership import (
            resolve_user_group_membership,
        )

        from uuid import UUID

        membership = resolve_user_group_membership()
        return sorted(membership.list_user_group_slugs(UUID(str(user.id))))

    def _serialise_details(self, details: Optional[UserDetails]) -> Optional[dict]:
        if details is None:
            return None
        return {field: getattr(details, field) for field in self._DETAILS_FIELDS}

    def import_(
        self,
        payload: dict,
        *,
        mode: str,
        dry_run: bool,
        allow_role_change: bool = False,
    ) -> ImportResult:
        rows = validate_envelope(payload, self.entity_key)
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        try:
            for index, row in enumerate(rows):
                self._import_row(
                    row, index, result, allow_role_change=allow_role_change
                )
        except Exception:
            self._session.rollback()
            raise
        if dry_run:
            self._session.rollback()
        else:
            self._session.commit()
        return result

    def _import_row(
        self,
        row: dict,
        index: int,
        result: ImportResult,
        *,
        allow_role_change: bool,
    ) -> None:
        email = row.get("email")
        if not email:
            result.errors.append(
                {"row": index, "reason": "missing natural key 'email'"}
            )
            return
        user = self._session.query(User).filter(User.email == email).first()
        if user is None:
            result.errors.append(
                {
                    "row": index,
                    "reason": f"unknown user '{email}'; create not supported",
                }
            )
            return
        self._apply(user, row, allow_role_change=allow_role_change)
        result.updated += 1

    def _apply(self, user: User, row: dict, *, allow_role_change: bool) -> None:
        if "status" in row and row["status"] is not None:
            user.status = row["status"]
        if "has_used_trial" in row:
            user.has_used_trial = bool(row["has_used_trial"])
        # Never elevate role/admin without explicit system permission (security R4).
        if allow_role_change and row.get("role"):
            user.role = row["role"]
        if "group_slugs" in row:
            self._apply_group_slugs(user, row["group_slugs"])
        details_payload = row.get("details")
        if isinstance(details_payload, dict):
            self._apply_details(user, details_payload)

    def _apply_group_slugs(self, user: User, group_slugs) -> None:
        # group_slugs round-trips by slug through the core membership port (the
        # exchanger never imports the UserGroup model directly). A CSV import
        # may pass a comma-joined string; normalise to a slug list.
        from vbwd.services.user_group_membership import (
            resolve_user_group_membership,
        )

        if isinstance(group_slugs, str):
            slugs = [part.strip() for part in group_slugs.split(",") if part.strip()]
        elif isinstance(group_slugs, (list, tuple)):
            slugs = [str(slug) for slug in group_slugs if slug]
        else:
            slugs = []
        from uuid import UUID

        resolve_user_group_membership().set_user_groups(UUID(str(user.id)), slugs)

    def _apply_details(self, user: User, details_payload: dict) -> None:
        details = user.details
        if details is None:
            details = UserDetails(user_id=user.id)
            self._session.add(details)
            user.details = details
        for field in self._DETAILS_FIELDS:
            if field in details_payload:
                setattr(details, field, details_payload[field])


# ── invoices (export-only) ───────────────────────────────────────────────────


class InvoicesExchanger(EntityExchanger):
    """Core invoices, export-only, keyed by the human invoice ``number``.

    Plugin-contributed invoice fields are handled by the separate
    ``invoice_extra_fields_registry`` — this exchanger only emits the core
    columns (UUIDs stripped). ``import_`` raises (Liskov).
    """

    entity_key = "invoices"
    label = "Invoices"
    cluster = CLUSTER_SALES
    natural_key = "number"
    supports_export = True
    supports_import = False
    supported_formats = frozenset({"json", "csv"})
    secret_fields = frozenset()
    pii_fields = frozenset()

    _CORE_FIELDS = (
        ("invoice_number", "number"),
        ("amount", "amount"),
        ("currency", "currency"),
        ("payment_method", "payment_method"),
        ("subtotal", "subtotal"),
        ("tax_amount", "tax_amount"),
        ("total_amount", "total_amount"),
    )

    def __init__(self, session: Any):
        self._session = session

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        invoices = self._session.query(UserInvoice).all()
        if selector.ids:
            wanted = {str(value) for value in selector.ids}
            invoices = [
                invoice
                for invoice in invoices
                if str(invoice.id) in wanted
                or (invoice.invoice_number and invoice.invoice_number in wanted)
            ]
        rows = [self._serialise(invoice) for invoice in invoices]
        return Envelope(entity_key=self.entity_key, rows=rows)

    def _serialise(self, invoice: UserInvoice) -> dict:
        row: dict = {}
        for column_name, export_name in self._CORE_FIELDS:
            value = getattr(invoice, column_name)
            row[export_name] = str(value) if value is not None else None
        row["status"] = invoice.status.value if invoice.status else None
        row["invoiced_at"] = (
            invoice.invoiced_at.isoformat() if invoice.invoiced_at else None
        )
        row["paid_at"] = invoice.paid_at.isoformat() if invoice.paid_at else None
        return row

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        raise UnsupportedOperationError("invoices is export-only")


# ── access_levels (Role + permission grants by natural key) ──────────────────


class AccessLevelsExchanger(EntityExchanger):
    """Admin access levels (``Role``), keyed by ``name``.

    The permission grants serialise as a list of permission *keys* (natural
    keys), so the envelope is instance-independent; import re-links by looking
    each permission up by name. Unknown permissions are skipped (reported).
    """

    entity_key = "access_levels"
    label = "Access Levels"
    cluster = CLUSTER_SETTINGS
    natural_key = "name"
    supports_export = True
    supports_import = True
    supported_formats = frozenset({"json"})
    secret_fields = frozenset()
    pii_fields = frozenset()

    def __init__(self, session: Any):
        self._session = session

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        roles = self._session.query(Role).all()
        if selector.ids:
            wanted = {str(value) for value in selector.ids}
            roles = [
                role
                for role in roles
                if str(role.id) in wanted or (role.name and role.name in wanted)
            ]
        rows = [self._serialise(role) for role in roles]
        return Envelope(entity_key=self.entity_key, rows=rows)

    def _serialise(self, role: Role) -> dict:
        return {
            "name": role.name,
            "slug": role.slug,
            "description": role.description,
            "is_system": bool(role.is_system),
            "permissions": sorted(perm.name for perm in list(role.permissions)),
        }

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        rows = validate_envelope(payload, self.entity_key)
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        try:
            for index, row in enumerate(rows):
                self._import_row(row, index, result)
        except Exception:
            self._session.rollback()
            raise
        if dry_run:
            self._session.rollback()
        else:
            self._session.commit()
        return result

    def _import_row(self, row: dict, index: int, result: ImportResult) -> None:
        name = row.get("name")
        if not name:
            result.errors.append({"row": index, "reason": "missing natural key 'name'"})
            return
        role = self._session.query(Role).filter(Role.name == name).first()
        if role is None:
            role = Role(name=name, slug=row.get("slug") or name.lower())
            self._session.add(role)
            result.created += 1
        else:
            result.updated += 1
        if "slug" in row and row["slug"]:
            role.slug = row["slug"]
        role.description = row.get("description")
        if "is_system" in row:
            role.is_system = bool(row["is_system"])
        self._relink_permissions(role, row.get("permissions") or [], index, result)

    def _relink_permissions(
        self, role: Role, permission_keys: list, index: int, result: ImportResult
    ) -> None:
        resolved: List[Permission] = []
        for key in permission_keys:
            permission = (
                self._session.query(Permission).filter(Permission.name == key).first()
            )
            if permission is None:
                result.errors.append(
                    {"row": index, "reason": f"unknown permission '{key}'"}
                )
                continue
            resolved.append(permission)
        # Mutate the relationship collection in place (clear + extend) rather
        # than reassigning, so the natural-key-resolved grants replace the old
        # set cleanly.
        grants = role.permissions
        grants.clear()
        grants.extend(resolved)


# ── email_templates (file-backed) ────────────────────────────────────────────


class EmailTemplatesExchanger(EntityExchanger):
    """Email templates, keyed by ``key`` (the template filename stem).

    Email templates are Jinja2 ``.html`` files on disk (there is no DB table).
    Two locations exist, matching :class:`EmailService`'s override-first
    loader: the **bundled defaults** shipped in the image and the **override
    dir** ``var/assets/core/email/templates`` (admin-editable, host-mounted).

    * Export emits the **effective** set: the union of both locations by
      filename, reading each file from its effective (override-first) location,
      so an export captures every template even before any override exists.
    * Import writes ``<key>.html`` into the override dir (created on first
      write), so imports take effect via the EmailService override path without
      mutating the bundled defaults.

    Each row is ``{key, content}``. ``replace_all`` is unsupported for a
    directory (refuses to delete operator templates).
    """

    entity_key = "email_templates"
    label = "Email Templates"
    cluster = CLUSTER_SETTINGS
    natural_key = "key"
    supports_export = True
    supports_import = True
    supported_formats = frozenset({"json", "csv"})
    secret_fields = frozenset()
    pii_fields = frozenset()

    def __init__(self, bundled_dir: str):
        self._bundled_dir = bundled_dir

    @property
    def _override_dir(self) -> str:
        # Resolved lazily so VBWD_VAR_DIR is honoured at call time (tests set it).
        return asset_dir("core", "email", "templates")

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        rows: List[dict] = []
        wanted = set(selector.ids) if selector.ids else None
        for key, path in sorted(self._effective_files().items()):
            if wanted is not None and key not in wanted:
                continue
            rows.append({"key": key, "content": self._read(path)})
        return Envelope(entity_key=self.entity_key, rows=rows)

    def _effective_files(self) -> dict:
        """Map template key -> effective file path (override wins over bundled)."""
        effective: dict = {}
        for directory in (self._bundled_dir, self._override_dir):
            for filename in self._template_filenames(directory):
                key = filename[: -len(EMAIL_TEMPLATE_SUFFIX)]
                effective[key] = os.path.join(directory, filename)
        return effective

    @staticmethod
    def _template_filenames(directory: str) -> List[str]:
        if not os.path.isdir(directory):
            return []
        return [
            name
            for name in os.listdir(directory)
            if name.endswith(EMAIL_TEMPLATE_SUFFIX)
        ]

    @staticmethod
    def _read(path: str) -> str:
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        rows = validate_envelope(payload, self.entity_key)
        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        if mode == MODE_REPLACE_ALL:
            raise UnsupportedOperationError(
                "email_templates does not support replace_all (file-backed)"
            )
        for index, row in enumerate(rows):
            self._import_row(row, index, result, dry_run=dry_run)
        return result

    def _import_row(
        self, row: dict, index: int, result: ImportResult, *, dry_run: bool
    ) -> None:
        key = row.get("key")
        content = row.get("content")
        if not key:
            result.errors.append({"row": index, "reason": "missing natural key 'key'"})
            return
        if content is None:
            result.errors.append({"row": index, "reason": "missing 'content'"})
            return
        override_dir = self._override_dir
        path = os.path.join(override_dir, f"{key}{EMAIL_TEMPLATE_SUFFIX}")
        existed = os.path.exists(path)
        if not dry_run:
            os.makedirs(override_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        if existed:
            result.updated += 1
        else:
            result.created += 1


# ── countries (wraps the legacy country_io — keeps Settings buttons working) ──


class CountriesExchanger(EntityExchanger):
    """Country catalog, keyed by ``code``.

    Delegates to :mod:`vbwd.services.country_io` so the Settings -> Countries
    export/import buttons (which still call those functions) and this exchanger
    share one implementation (DRY) and produce identical output.
    """

    entity_key = "countries"
    label = "Countries"
    cluster = CLUSTER_SETTINGS
    natural_key = "code"
    supports_export = True
    supports_import = True
    supported_formats = frozenset({"json", "csv"})
    secret_fields = frozenset()
    pii_fields = frozenset()

    def __init__(self, session: Any):
        self._session = session

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        from vbwd.services.country_io import export_countries

        rows = export_countries(self._session)["countries"]
        if selector.ids:
            wanted = set(selector.ids)
            rows = [row for row in rows if row["code"] in wanted]
        return Envelope(entity_key=self.entity_key, rows=rows)

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        from vbwd.services.country_io import import_countries

        result = ImportResult(entity=self.entity_key, mode=mode, dry_run=dry_run)
        if dry_run:
            # country_io commits; for a dry run we count without writing.
            return self._dry_run_count(payload, result)
        outcome = import_countries(self._session, payload)
        result.created = outcome.created
        result.updated = outcome.updated
        return result

    def _dry_run_count(self, payload: dict, result: ImportResult) -> ImportResult:
        rows = payload.get("countries")
        if not isinstance(rows, list):
            return result
        for row in rows:
            code = row.get("code") if isinstance(row, dict) else None
            if not code:
                continue
            existing = self._session.query(Country).filter(Country.code == code).first()
            if existing is not None:
                result.updated += 1
            else:
                result.created += 1
        return result


# ── factory + registration ───────────────────────────────────────────────────


def build_core_exchangers(
    session: Any, *, email_template_dir: Optional[str] = None
) -> List[EntityExchanger]:
    """Construct the core exchangers bound to ``session``.

    ``email_template_dir`` overrides the bundled email-template default dir
    (used in tests); the admin-override dir is always ``var/assets/core/email/
    templates`` resolved at runtime.
    """
    template_dir = email_template_dir or DEFAULT_EMAIL_TEMPLATE_DIR
    return [
        UsersExchanger(session),
        InvoicesExchanger(session),
        _build_payment_methods_exchanger(session),
        AccessLevelsExchanger(session),
        EmailTemplatesExchanger(template_dir),
        _build_currencies_exchanger(session),
        CountriesExchanger(session),
        _build_token_bundles_exchanger(session),
        _build_taxes_exchanger(session),
        _build_user_groups_exchanger(session),
        _build_tags_exchanger(session),
        CustomFieldDefsExchanger(session),
    ]


def register_core_exchangers(
    session: Any, *, email_template_dir: Optional[str] = None
) -> None:
    """Register the core exchangers into the global registry (idempotent).

    Called from ``create_app`` at init, before the permission catalog is
    collected, so the sales-cluster export/import/PII permissions surface in the
    Access Level form. Re-registering replaces by key, so this is clear-safe.
    """
    for exchanger in build_core_exchangers(
        session, email_template_dir=email_template_dir
    ):
        data_exchange_registry.register(exchanger)
