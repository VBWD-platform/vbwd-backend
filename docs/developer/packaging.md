# Packaging & pip installation

**Status:** implemented 2026-07-05 — every VBWD backend repo (core + 37 plugins) is
now a valid PEP 517 project and installable with `pip install "git+…@<ref>"`.

This document is the source of truth for how `vbwd-backend` and its plugins are
packaged. The other repos (`vbwd-sdk-private`, `vbwd-platform`,
`vbwd-demo-instances`) link here rather than duplicating it.

---

## TL;DR

```bash
# Core
pip install "git+https://github.com/VBWD-platform/vbwd-backend.git@main"

# Any plugin (repo name is vbwd-plugin-<slug>)
pip install "git+https://github.com/VBWD-platform/vbwd-plugin-cms.git@main"
pip install "git+https://github.com/VBWD-platform/vbwd-plugin-shop.git@main"

# Pin a release
pip install "git+https://github.com/VBWD-platform/vbwd-plugin-shop.git@v26.6.1"
```

There is **no PyPI/private index** and nothing to "register" — a repo is
git-pip-installable the moment its `pyproject.toml` carries a valid
`[build-system]` + `[project]`. Private repos install over your GitHub auth
(SSH URL or a PAT).

---

## The two packaging shapes

### Core — `vbwd-backend`

Standard `src`-less layout: `pyproject.toml` at the repo root ships the top-level
`vbwd/` package and **excludes** `plugins*` and `tests*`.

```toml
[tool.setuptools.packages.find]
include = ["vbwd*"]
exclude = ["tests*", "plugins*"]
```

Installing the core wheel gives you `import vbwd…` (Routes → Services →
Repositories → Models, the plugin base classes, pricing, security, etc.). It does
**not** carry any plugin.

### Plugins — `vbwd-plugin-<slug>`

Each plugin lives in its own repo, and **the repo root *is* the monorepo's
`plugins/<name>/` directory**. At runtime the host imports it as
`plugins.<name>` and plugins cross-import each other by that absolute path, e.g.:

```python
# plugins/shop/__init__.py
from plugins.shop.shop.shipping_registry import ShippingMethodRegistry
```

So the wheel **must** expose the `plugins.<name>` package, not a bare top-level
module. That is achieved with a `package-dir` remap of the repo root:

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "vbwd-plugin-shop"
version = "26.6.1"
requires-python = ">=3.11"
license = { text = "BSL-1.1" }
dependencies = []          # third-party deps only, pulled from requirements.txt

[tool.setuptools]
package-dir = { "plugins.shop" = "." }   # repo root -> plugins.shop
packages = [
    "plugins.shop",
    "plugins.shop.shop",
    "plugins.shop.shop.handlers",
    # …every real subpackage, tests/docs/bin excluded…
]

[tool.setuptools.package-data]
"plugins.shop" = [                       # everything a pip-installed plugin needs
    "*.json",                            # config.json + admin-config.json
    "migrations/*.py", "migrations/**/*.py", "migrations/*.mako", "migrations/*.ini",
    "populate_db.py", "populate_*.py", "demo_seed.py",
    "bin/*", "bin/**/*",
]
```

The wheel then lays out `plugins/shop/__init__.py`, `plugins/shop/shop/…`,
`plugins/shop/config.json`, `plugins/shop/migrations/versions/*.py`, etc. —
identical to the runtime import path, and self-complete (code + migrations +
seed + config), so a `pip install`ed plugin can migrate and seed.

This shape is **layout-agnostic**: it is the same whether the plugin keeps its
code in a `src/` folder (analytics, chat, cms, email, ghrm, mailchimp, tarot) or
flat beside `__init__.py` (everything else). The only difference is which
subpackages get enumerated.

---

## Pip-install into the host (enabled 2026-07-05)

Plugins can now be `pip install`ed **into a running host** — the image build and
the platform metapackage both do this instead of cloning. Three things make it
work, all agnostic (no plugin names hard-coded):

1. **`plugins` is a namespace package.** `plugins/__init__.py` is a one-line
   `pkgutil.extend_path` shim, so every `plugins/` directory on `sys.path` merges
   into one `plugins.__path__`. A locally-cloned `plugins/<name>/` and a
   `pip install`ed `vbwd-plugin-<name>` (which lands in
   `site-packages/plugins/<name>/`) are both importable as `plugins.<name>`.
   (The core wheel excludes `plugins*`, so a pure-pip install has no
   `plugins/__init__.py` at all — an implicit PEP 420 namespace — and still
   merges. The shim only matters when `/app/plugins/__init__.py` is baked in by
   `COPY . .`.)

2. **Wheels are self-complete.** Package-data ships each plugin's
   `migrations/**`, `populate_db.py` / seed scripts, `bin/**`, and config JSON —
   not just importable code — so a pip-installed plugin can migrate and seed.

3. **Alembic discovers migrations via the namespace.** `alembic/env.py` iterates
   `plugins.__path__` (not a hard-coded `./plugins`) to build `version_locations`
   and to import plugin models. It therefore finds clone-based **and**
   pip-installed migrations identically, with no per-plugin config in
   `alembic.ini`.

Verified end-to-end: `pip install vbwd-backend + vbwd-plugin-shop` into a clean
venv → `plugins` is a namespace, `plugins.shop` imports (transitive `vbwd.*`
resolves from the core wheel), and `env.py`'s discovery finds shop's migrations.

> **Hard prerequisite:** the pip path is inert until each plugin repo's
> `pyproject.toml` (with the migrations-shipping package-data) is committed and
> pushed to its `main`. Until then `pip install git+…@main` fails with
> *"neither setup.py nor pyproject.toml found"*.

---

## Who consumes these packages

**pip-install is for platform development only.** The SDK recipes and the
demo-instances prod deploy stay **clone-based** — pip is not on the deploy path.

| Consumer | Core | Plugins |
|---|---|---|
| **`vbwd-platform`** (metapackage — *the* pip consumer) | pip git-install via `be/requirements.txt` (`vbwd-backend @ git+…@main`) | **pip-installed** from `be/plugins-requirements.txt` (generated from `plugins.json`) via `make install-plugins-pip` |
| **`vbwd-demo-instances`** prod deploy (`deploy.yml`) | baked into the image | **cloned** into `vbwd-backend/plugins/` + `COPY` (clone model) |
| **`vbwd-sdk-private` / `vbwd-sdk-public`** dev recipes | cloned to `../vbwd-backend` by `dev-install-ce.sh` | cloned by the declarative `PLUGIN_REGISTRY` |
| **Ad-hoc / CI / downstream** | `pip install git+…` | `pip install git+…` for any single plugin |

The Dockerfile plugin-install step is **guarded** (`if [ -s plugins-requirements.txt ]`)
and has `set -e`, so: a consumer that does *not* provide that file (demo-instances,
SDK, backend test CI) uses the clone model unchanged; a consumer that *does*
(platform) fails the build loudly if any plugin can't install — never a silent
plugin-less image. The pip path is strictly additive.

**No hyphenated import packages** (2026-07-06). `cms-ai` and `loopai-adapter`
previously used hyphenated dirs → `plugins.cms-ai` is an invalid Python package
name → wheel build failed (the 2026-07-05 incident). They were **renamed** to
underscore *import* identities — `plugins.cms_ai`, `plugins.loopai_adapter` (dir +
inner dir + dotted imports) — while keeping their **public** identity (dist
`vbwd-plugin-cms-ai`/`-loopai-adapter`, `metadata.name` `cms-ai`/`loopai-adapter`,
URLs `/api/v1/plugins/cms-ai` & `/api/v1/loopai-adapter`). Only dotted
`plugins.<name>` imports were rewritten — never the slash URLs. So **every backend
plugin is now pip-wheelable**; proven on platform CI (`platform_tests` pip-installs
all backend incl. these two and asserts their routes register).

---

## Adding packaging to a new plugin

A new `plugins/<name>/` needs a `pyproject.toml` following the shape above.
Mechanically:

1. `name` = the repo/dist name `vbwd-plugin-<slug>` (matches `git remote`).
2. `version` = the plugin's `PluginMetadata.version` (keep them in sync).
3. `package-dir = { "plugins.<name>" = "." }`.
4. `packages` = `plugins.<name>` plus every subdir containing an `__init__.py`
   (exclude `tests`, `docs`, `bin`, `__pycache__`).
5. `dependencies` = third-party runtime deps only (mirror `requirements.txt` if
   present). **Do not** pin `vbwd-backend` or sibling plugins — the host provides
   `vbwd.*` and declares plugin→plugin deps in `PluginMetadata.dependencies`.
6. `[tool.setuptools.package-data]` ships `*.json` **plus** `migrations/**`,
   `populate_db.py`/seed scripts, and `bin/**` so the wheel is self-complete for
   the pip-install path.

Preserve any existing `[tool.black]` / tool config already in the file. All of
this is produced automatically by the generator (see below) — you rarely hand-write it.

### Verify the wheel

```bash
python3 -m pip wheel ./plugins/<name> --no-deps -w /tmp/wheels
python3 -m zipfile -l /tmp/wheels/vbwd_plugin_<slug>-*.whl | grep -E '^plugins/<name>/(migrations/versions/|__init__|config)'
```

You should see `plugins/<name>/__init__.py`, the subpackages, the JSON config,
**and** `migrations/versions/*.py`. (Building does not import the code, so missing
runtime deps don't break the build.) Clean up the `build/` + `*.egg-info`
artifacts afterwards — some plugin `.gitignore`s cover them, some don't yet.

### The generator

All 37 plugin `pyproject.toml` files are produced by a single introspecting
generator (dist name from the git remote, `package-dir` remap, subpackage
enumeration, package-data, deps from `requirements.txt`, idempotent, preserves
`[tool.black]`). Re-run it after adding a plugin rather than hand-editing. It is
not yet committed to `bin/`; ask if you want it dropped in.

---

## Notes

- All plugins are currently version `26.6.1`, matching core.
- Four `plugins/` entries are **not** packaged because they are not standalone
  repos: `demoplugin` (test fixture), `log_shipper_loki`, `shop_pharma`.
- The `vbwd-backend.egg-info/` in the repo is a stale build artifact (shows
  `0.1.0`); `pyproject.toml` (`26.6.1`) is authoritative.
