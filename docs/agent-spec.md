# AgentSpec reference (v1alpha1)

An agent is one YAML (or JSON) file. Full example: [`examples/dental-clinic/agent.yaml`](../examples/dental-clinic/agent.yaml). Design: [ADR-0005](adr/0005-declarative-agent-spec.md).

```sh
uv run ringbridge agent validate examples/*/agent.yaml       # errors fail, warnings pass
uv run ringbridge agent validate --strict --json agent.yaml   # warnings fail too; JSON output
uv run ringbridge agent schema > agent-v1alpha1.json          # the JSON Schema
```

**Editor autocompletion:** add this first line to your file (VS Code with the YAML extension, JetBrains, Neovim with yaml-language-server):

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/annmary-ann/ringbridge/main/docs/schema/agent-v1alpha1.json
```

## Shape

```yaml
apiVersion: ringbridge.dev/v1alpha1
kind: Agent
metadata: { name: my-agent, description: optional }
spec:
  language:    { default: en-IN, allowed: [hi-IN], detect: true }
  voice:       { engine: cascaded, stt: {...}, llm: {...}, tts: {...}, overrides: { hi-IN: {...} } }
  persona:     "Who the agent is and how it talks."
  disclosures: { greeting: "Hi, this is ... an AI assistant. This call is recorded." }
  business:    { timezone: Asia/Kolkata, hours: { mon-sat: "09:00-19:00", sun: closed }, knowledge: [...] }
  graph:       { start: triage, nodes: { triage: {...}, booking: {...} } }
  post_call:   { extract: {...}, follow_ups: [...] }
```

Unknown keys are errors everywhere, so a typo like `persnoa:` is caught instead of ignored.

## Nodes

A node is either a **conversation** (`goal`) or a built-in **action** (`action: transfer`).

| Key | Meaning |
|---|---|
| `goal` | What the agent tries to achieve in this step |
| `collect` | Typed slots that must be filled before leaving: `string`, `enum` (with `values`), `number`, `boolean`, `date`, `time`, `datetime_window`, `phone`, `email` |
| `tools` | Tools the LLM may call **in this node only** |
| `guardrails` | `confirm_before: <tool>`: read back and get an explicit yes first |
| `transitions` | `{ to: <node>, when: <condition> }` |
| `max_turns`, `silence_timeout_s` | Per-node limits |
| `action: transfer` + `transfer` | `{ mode: warm\|cold, to: <E.164>, brief, fallback: take_message\|end_call, ring_timeout_s }` |

Built-in tools: `calendar.availability`, `calendar.book`, `calendar.reschedule`, `calendar.cancel`, `crm.lookup_contact`, `message.send`, `call.transfer`, `call.end`. Custom HTTP and MCP tools come later (#30, #43).

## Post-call

- `extract` declares the outcome schema the post-call workflow fills: `string` (optional `max_words`), `enum`, `number` or `boolean`.
- `follow_ups` run when their `when` condition matches. A condition may use the extracted fields plus `attempt`, `direction` and `duration_s`. Each follow-up has exactly one action:
  - `send: { channel, template, fallback }`
  - `schedule_call: { after: 30m|2h|1d, within_window }`

## What the validator checks

**Errors**, which fail validation:
- wrong types, missing fields, unknown keys, bad formats (names, locales, E.164 numbers, hours)
- the start node or a transition target doesn't exist
- an unknown tool, or `confirm_before` naming a tool the node doesn't have
- a missing disclosure greeting
- an unknown time zone
- an override for a locale that isn't allowed
- a follow-up condition using an unknown name
- a follow-up with zero or two actions

**Warnings**, which pass unless `--strict`:
- unreachable nodes
- side-effect tools without `confirm_before`
- no way to end or transfer the call
- the disclosure check turned off
- `detect` with no other locales

Every message includes the file, the line and the path, e.g.:

```
agent.yaml:23: error: spec.graph.nodes.greet.guardrails[0].confirm_before: confirm_before 'calendar.book' is not in this node's tools
```

The schema in `docs/schema/` is generated from the models (`uv run poe schema`). A test fails if it goes stale.
