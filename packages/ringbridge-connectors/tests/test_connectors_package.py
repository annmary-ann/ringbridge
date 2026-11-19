from importlib.metadata import version

import ringbridge_connectors


def test_version_matches_distribution_metadata() -> None:
    assert ringbridge_connectors.__version__ == version("ringbridge-connectors")
