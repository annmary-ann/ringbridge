"""AgentSpec v1alpha1: models, validation and JSON Schema (ADR-0005)."""

import json
from typing import Any

from ringbridge_core.spec.issues import Issue, Severity
from ringbridge_core.spec.loader import Report, load_file, load_text
from ringbridge_core.spec.models import API_VERSION, AgentSpec
from ringbridge_core.spec.tools import BUILTIN_TOOLS


def json_schema() -> dict[str, Any]:
    """The published JSON Schema for AgentSpec files (by alias, so `apiVersion` stays camelCase)."""
    return AgentSpec.model_json_schema(by_alias=True)


def json_schema_text() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True) + "\n"


__all__ = [
    "API_VERSION",
    "BUILTIN_TOOLS",
    "AgentSpec",
    "Issue",
    "Report",
    "Severity",
    "json_schema",
    "json_schema_text",
    "load_file",
    "load_text",
]
