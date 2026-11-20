# Ringbridge

[![CI](https://github.com/annmary-ann/ringbridge/actions/workflows/ci.yml/badge.svg)](https://github.com/annmary-ann/ringbridge/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Open-source voice agents that run real business phone calls.**

Ringbridge answers your calls and makes them for you. It qualifies callers, books appointments, calls leads, leaves voicemails, updates your CRM, sends the follow-up text, and hands off to a person when it should. It is self-hosted, works with any STT, LLM, TTS and SIP provider, and supports global English and Indian languages.

> **Status: pre-alpha, being designed in public.** Nothing here is usable yet. Follow the [roadmap](#roadmap) or read the [architecture](docs/architecture.md).

## Why

- **Hosted voice-agent platforms** are easy to use, but you rent them per minute, can't self-host them, and can't see inside.
- **Open-source voice frameworks** are excellent real-time pipelines, but every team still rebuilds booking, CRM sync, campaigns, compliance and testing.

Ringbridge is the business layer on top of an open real-time voice stack ([LiveKit](https://github.com/livekit/agents)).

## What it will do

| | |
|---|---|
| 📞 **Inbound** | Answer, qualify, answer FAQs, book, reschedule or cancel appointments |
| 📤 **Outbound** | Call lead lists within local calling hours, detect voicemail, leave a message, retry |
| 🗂️ **CRM sync** | Summary, transcript, outcome and lead status on every call (HubSpot first; connector SDK for the rest) |
| 💬 **Follow-up** | SMS, WhatsApp or email chosen by call outcome |
| 🙋 **Handoff** | Warm transfer with a spoken brief, or take a message when nobody picks up |
| 🧪 **Simulation tests** | LLM-played callers test every agent in CI before a change ships |
| 📈 **Observability** | OpenTelemetry trace per call, per-turn latency and cost |
| 🛡️ **Compliance built in** | AI and recording disclosure, consent, do-not-call, calling windows, PII redaction |
| 🌏 **Multilingual** | English, Hindi, then Malayalam and Tamil, with code-switching |

## How an agent looks

Agents are versioned YAML: a small state graph for the steps that must be reliable, natural LLM conversation inside each step.

```yaml
graph:
  start: triage
  nodes:
    booking:
      goal: Collect details and book a slot.
      collect:
        name: { type: string }
        preferred_time: { type: datetime_window }
      tools: [calendar.availability, calendar.book]
      guardrails:
        - confirm_before: calendar.book   # never books without a spoken "yes"
```

Full example in [docs/architecture.md §4](docs/architecture.md#4-agent-model-agentspec).

## Architecture

```
Phone ─SIP─► LiveKit SIP ─► Agent workers (STT → LLM → TTS, graph runtime)
                                   │ tools / events
                                   ▼
             Control plane (FastAPI) + durable workflows on Postgres
                                   │ outbox
                                   ▼
             Connectors: calendar · CRM · SMS / WhatsApp / email · HTTP · MCP
```

- [Architecture](docs/architecture.md)
- [Architecture decision records](docs/adr/)

## Roadmap

| Milestone | Target | |
|---|---|---|
| M0 Foundations | Nov 2026 | Monorepo, CI, dev stack, telephony spike |
| M1 Voice core | Dec 2026 | A phone number answered by an agent from YAML, traced |
| M2 Receptionist **v0.1** | Jan 2027 | Booking, CRM, follow-ups, handoff, simulation tests in CI |
| M3 Outbound + India **v0.2** | Feb 2027 | Campaigns, voicemail, retries, DNC, WhatsApp, Hindi |
| M4 Platform **v0.3** | Mar 2027 | Multi-tenant API, dashboard, voice-mode simulation |
| M5 **v1.0** | Apr 2027 | Helm, security review, docs site, published benchmarks |

Progress is tracked on the [project board](https://github.com/users/annmary-ann/projects/8).

## Contributing

Ideas and design feedback are very welcome now. Open an issue or comment on an ADR. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[Apache-2.0](LICENSE)
