from importlib.metadata import version

import ringbridge_sim


def test_version_matches_distribution_metadata() -> None:
    assert ringbridge_sim.__version__ == version("ringbridge-sim")
