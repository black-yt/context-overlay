from importlib.metadata import version

import context_overlay


def test_version_matches_package_metadata() -> None:
    assert context_overlay.__version__ == version("context-overlay")
