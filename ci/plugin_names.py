"""Print ``<directory><TAB><PluginMetadata.name>`` for every plugin present.

The two differ for the bot plugins (directory ``bot_base``, registry name
``bot-base``). CI steps that walk ``plugins/*/`` therefore have a directory in
hand but must address the plugin by its registry name — ``flask plugins enable
bot_telegram`` reports success yet writes an entry keyed by the directory,
which the loader then skips ("Persisted plugin 'bot_telegram' not found in
registry"). The plugin never enables, its blueprint never mounts, and route
tests fail with 404.

Emitting both halves lets a caller keep matching exclude-lists by directory
while enabling by name.

Usage (from the backend root)::

    python ci/plugin_names.py
"""
import os
import sys

from missing_plugin_deps import PLUGINS_ROOT, _parse, _string_keyword


def plugin_names() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for directory in sorted(os.listdir(PLUGINS_ROOT)):
        init_path = os.path.join(PLUGINS_ROOT, directory, "__init__.py")
        if not os.path.isfile(init_path):
            continue
        tree = _parse(init_path)
        names = _string_keyword(tree, "name") if tree is not None else []
        pairs.append((directory, names[0] if names else directory))
    return pairs


def main() -> int:
    for directory, name in plugin_names():
        sys.stdout.write(f"{directory}\t{name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
