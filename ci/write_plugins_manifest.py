"""Write a plugins.json that enables every plugin present in plugins/.

The manifest key must be the plugin's ``PluginMetadata.name``, not its
directory. Those differ for the bot plugins (directory ``bot_base``, name
``bot-base``), and a key that does not match the registry name is silently
ignored at load time: the plugin never enables, so its routes 404 while
everything *looks* configured.

Usage (from the backend root)::

    python ci/write_plugins_manifest.py [path]   # default plugins/plugins.json
"""
import json
import os
import sys

from missing_plugin_deps import PLUGINS_ROOT, _parse, _string_keyword


def build_manifest() -> dict:
    plugins: dict[str, dict] = {}
    for directory in sorted(os.listdir(PLUGINS_ROOT)):
        init_path = os.path.join(PLUGINS_ROOT, directory, "__init__.py")
        if not os.path.isfile(init_path):
            continue
        tree = _parse(init_path)
        if tree is None:
            continue
        names = _string_keyword(tree, "name")
        # Fall back to the directory when a plugin declares no metadata name —
        # better a wrong-but-visible key than dropping the plugin entirely.
        key = names[0] if names else directory
        plugins[key] = {"enabled": True, "version": "1.0.0", "source": "local"}
    return {"plugins": plugins}


def main() -> int:
    target = (
        sys.argv[1] if len(sys.argv) > 1 else os.path.join(PLUGINS_ROOT, "plugins.json")
    )
    manifest = build_manifest()
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    names = sorted(manifest["plugins"])
    print(f"Wrote {target} enabling {len(names)} plugins: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
