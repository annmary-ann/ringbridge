from importlib.metadata import version

import ringbridge_agent


def test_version_matches_distribution_metadata() -> None:
    assert ringbridge_agent.__version__ == version("ringbridge-agent")
