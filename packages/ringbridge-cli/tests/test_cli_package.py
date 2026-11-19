from importlib.metadata import version

import ringbridge_cli


def test_version_matches_distribution_metadata() -> None:
    assert ringbridge_cli.__version__ == version("ringbridge-cli")
