"""Tests for the generic asset-storage path helper.

``asset_dir(owner, *parts)`` is core infrastructure: it resolves the on-disk
home of editable/runtime assets under ``${VBWD_VAR_DIR}/assets/<owner>/...``.
``owner`` is ``"core"`` or a plugin id; the helper is domain-agnostic and
imports nothing from plugins.
"""
import os

from vbwd.services.asset_storage import asset_dir


class TestAssetDir:
    def test_honors_vbwd_var_dir_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
        result = asset_dir("core", "email", "templates")
        assert result == os.path.join(
            str(tmp_path), "assets", "core", "email", "templates"
        )

    def test_defaults_to_app_var_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("VBWD_VAR_DIR", raising=False)
        result = asset_dir("core", "email", "templates")
        assert result == os.path.join(
            "/app/var", "assets", "core", "email", "templates"
        )

    def test_owner_only(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
        assert asset_dir("meinchat") == os.path.join(
            str(tmp_path), "assets", "meinchat"
        )

    def test_plugin_owner_namespacing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
        assert asset_dir("cms", "media") == os.path.join(
            str(tmp_path), "assets", "cms", "media"
        )
