# ADR-0005: Declarative, versioned AgentSpec with a state graph and LLM nodes

- Status: Accepted
- Date: 2026-11-19

## Context
Pure prompt agents are flexible but fail unpredictably on the steps that matter: they book without confirming, skip required fields, or forget to transfer. Pure flow builders (IVR trees) are reliable but sound robotic and break on anything unexpected.

## Decision
Agents are defined by an **AgentSpec** (YAML/JSON, `apiVersion: ringbridge.dev/v1alpha1`):
- a small **graph** of nodes, each with a goal, typed `collect` slots, an allowed tool list, guardrails and transitions;
- free LLM conversation inside a node;
- runtime-enforced rules: slot validation before transitions, `confirm_before` for side-effecting tools, per-node tool scoping, global intents (human, opt-out, "are you a robot") on every turn, turn and silence limits.

Specs are validated by a JSON Schema generated from Pydantic models. Published versions are immutable. Numbers and campaigns reference a version.

## Alternatives considered
- Code-only agents (Python classes). Powerful but not editable from a dashboard and hard to diff or review. Code is still allowed for custom tools.
- A visual flow builder as the source of truth. That can come later as a view over the same spec.

## Consequences
The graph engine is core IP and must be very well tested: unit tests per rule, and simulation scenarios per example agent.
