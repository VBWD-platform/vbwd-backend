"""Shared DI-registration helpers for plugin ``on_enable`` (S09).

The subscription plugin showed the canonical pattern for registering a
plugin's repositories with the DI container so other plugins / core
routes can resolve them via ``container.<name>_repository()``. Without
this step, plugins that own repos break the moment another plugin or
route tries to resolve through the container (the 2026-03-27 checkout
outage was exactly this — subscription extraction forgot to register
the providers; see memory ``project_plugin_di_provider_registration``).

S09 extracts the boilerplate into one helper so:
  (a) every plugin's ``on_enable`` reads the same way (§5 DRY), and
  (b) the registration semantics live in one home — future hardening
      (locks, per-app scoping, unregister-on-disable) lands here, not
      duplicated across every plugin.

Usage (in a plugin's ``on_enable``):

    from flask import current_app
    from vbwd.plugins.di_helpers import register_repositories
    from plugins.myplug.myplug.repositories.foo_repository import FooRepository
    from plugins.myplug.myplug.repositories.bar_repository import BarRepository

    container = getattr(current_app, "container", None)
    if container is not None:
        register_repositories(container, {
            "myplug_foo_repository": FooRepository,
            "myplug_bar_repository": BarRepository,
        })

Naming convention: ``<plugin>_<repo_snake>`` to avoid collisions with
core's ``user_repository``, ``invoice_repository``, etc.
"""
from __future__ import annotations

from typing import Mapping, Type


def register_repositories(container, repos: Mapping[str, Type]) -> None:
    """Register each repo class as a ``providers.Factory(cls, session=db_session)``
    on the container under the supplied attribute name.

    Idempotent: re-registering the same name overwrites the previous
    binding (matches dependency_injector's setattr semantics).
    """
    from dependency_injector import providers

    for provider_name, repository_class in repos.items():
        setattr(
            container,
            provider_name,
            providers.Factory(repository_class, session=container.db_session),
        )


def unregister_repositories(container, provider_names) -> None:
    """Remove the given provider attributes from the container.

    No-op for names that aren't present (so calling on_disable twice is safe).
    Mirror of :func:`register_repositories` — call from ``on_disable``.
    """
    for provider_name in provider_names:
        if hasattr(container, provider_name):
            delattr(container, provider_name)
