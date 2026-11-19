from importlib.metadata import version

import ringbridge_core


def test_version_matches_distribution_metadata() -> None:
    assert ringbridge_core.__version__ == version("ringbridge-core")
