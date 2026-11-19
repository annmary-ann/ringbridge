from importlib.metadata import version

import ringbridge_server


def test_version_matches_distribution_metadata() -> None:
    assert ringbridge_server.__version__ == version("ringbridge-server")
