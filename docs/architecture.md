# Ringbridge architecture

> Status: **draft v0.1 design** (Nov 2026). Decisions are recorded as ADRs in [`docs/adr/`](adr/). Where this document and an ADR disagree, the ADR wins.

## 1. What Ringbridge is

Ringbridge is an open-source, self-hostable platform for **voice agents that run real business phone calls**:

- **Inbound:** answer calls, qualify the caller, answer questions, book, reschedule or cancel appointments.
- **Outbound:** call leads from a list, detect voicemail and leave a message, retry on a schedule.
- **After the call:** write a summary, transcript, outcome and lead status to the CRM, then send a text, WhatsApp or email based on how the call went.
- **Hand off** to a real person (warm or cold transfer) when the caller asks or the agent is stuck.

Ringbridge is the **business layer** on top of an open real-time voice stack. Hosted platforms (Retell, Vapi, Bland) give you this behind a per-minute API you cannot self-host. Open frameworks (LiveKit Agents, Pipecat) give you an excellent real-time pipeline, but every team rebuilds booking, CRM sync, campaigns, compliance and testing. Ringbridge fills that gap.

### Design goals

1. **Reliable on real calls.** Critical steps (confirming a booking, collecting consent, transferring) are deterministic. The LLM never "decides" to book without a spoken confirmation.
2. **Fast.** Median voice-to-voice latency under 800 ms on a cascaded pipeline (see §6).
3. **Provider-neutral.** Any STT, LLM, TTS or SIP trunk. Swapping one is a config change, not a code change.
4. **Global English and Indian languages from the start.** Language is a first-class setting, not a translation layer added later.
5. **Testable.** Every agent ships with simulated-caller scenarios that run in CI. A change that breaks booking fails the build.
6. **Observable.** Every turn is traced: STT, LLM, TTS and end-of-turn timings, tokens and cost.
7. **Compliant by default.** Recording disclosure, AI disclosure, consent, do-not-call lists and calling-hour windows are product features.
8. **Easy to self-host.** `docker compose up` runs the whole stack on one machine. No Kafka, no Temporal cluster.

### Non-goals (for v1)

- A general-purpose contact-centre suite (IVR trees, human agent queues, workforce management).
- Training our own STT, TTS or LLM models.
- A no-code website builder. The dashboard configures agents. It is not a marketing site generator.
- Video calls.

## 2. System context

```
                ┌──────────────┐        ┌───────────────────────────────┐
  Caller ─PSTN─►│ SIP trunk    │──SIP──►│ LiveKit server + LiveKit SIP  │
  (phone)       │ Twilio/Telnyx│        │ (rooms, media, SIP bridge)    │
                │ Plivo/Exotel │        └──────────────┬────────────────┘
                └──────────────┘                       │ dispatch
                                                       ▼
                                        ┌───────────────────────────────┐
     STT / LLM / TTS providers ◄───────►│ Agent workers (Python)        │
     Deepgram, OpenAI, Anthropic,       │ ringbridge-agent              │
     Cartesia, ElevenLabs, Sarvam ...   │ AgentSpec → graph runtime     │
                                        └──────┬───────────────┬────────┘
                                   tools (HTTP)│               │ call events
                                               ▼               ▼
  Dashboard / API clients ─────────► ┌───────────────────────────────────┐
                                     │ Control plane (FastAPI)           │
                                     │ ringbridge-server                 │
                                     │ agents · numbers · contacts ·     │
                                     │ campaigns · calls · webhooks      │
                                     ├───────────────────────────────────┤
                                     │ Durable workflows (Postgres)      │
                                     │ post-call · outbox · campaigns ·  │
                                     │ follow-ups · retries              │
                                     └──────┬──────────────────┬─────────┘
                                            ▼                  ▼
                                 Postgres 16 + S3 (MinIO)   Connectors
                                 state, transcripts,        Calendar · CRM ·
                                 recordings                 SMS/WhatsApp/email
                                                            HTTP tools · MCP

     OpenTelemetry (traces, metrics) from every component → any OTLP backend
```

## 3. Components

### 3.1 Media layer: LiveKit server + LiveKit SIP

- **LiveKit server** (open source, Go) hosts a *room* per call. **LiveKit SIP** bridges SIP trunks into rooms for inbound and outbound calls. It also performs transfers (SIP REFER) and DTMF.
- Phone numbers belong to the business's own SIP trunk provider (bring your own trunk, see [ADR-0008](adr/0008-telephony-byo-sip-trunk.md)). Ringbridge configures the inbound trunk and dispatch rules through the LiveKit API.
- Web calls (a "talk to our agent" button) use the same rooms over WebRTC, with no telephony.

Why LiveKit: [ADR-0002](adr/0002-livekit-agents-runtime.md).

### 3.2 Agent workers: `ringbridge-agent`

A Python worker built on LiveKit Agents. Per call it:

1. Loads the **published AgentSpec version** bound to the dialled number or the campaign.
2. Builds the voice pipeline from the spec's provider config: VAD → STT → turn detection → LLM → TTS, with interruption (barge-in) handling.
3. Runs the **conversation graph** (§4). Each node maps to a LiveKit `Agent` with its own instructions and tools, and transitions are agent handoffs.
4. Calls **tools**: built-ins backed by connectors (check availability, book, look up contact, transfer, send message, end call), HTTP webhook tools, and MCP servers.
5. Streams **call events** to the control plane: turn segments, tool calls, node transitions, latency metrics. Events are batched and idempotent (event id per turn).
6. On disconnect, emits `call.ended`, which starts the post-call workflow.

Workers are stateless and horizontally scalable. All durable state lives in the control plane.

### 3.3 Control plane: `ringbridge-server`

FastAPI + SQLAlchemy 2 + Alembic on Postgres 16.

- **Resources:** organisations, projects, API keys, agents and agent versions, phone numbers, SIP trunks, contacts, consents, DNC entries, campaigns, calls, connector installs, message templates, follow-up rules, simulation scenarios and runs.
- **Public REST API** (OpenAPI 3.1) plus signed **outgoing webhooks** (`call.started`, `call.ended`, `call.analyzed`, `booking.created`, ...), HMAC-SHA256 with timestamp.
- **Internal API** for agent workers (call config fetch, event ingestion, tool execution), authenticated with short-lived worker tokens.
- **Multi-tenancy:** every row carries `project_id`, enforced by Postgres row-level security ([ADR-0009](adr/0009-multi-tenancy-rls.md)).

### 3.4 Durable workflows

Anything that must survive a crash or retry runs as a durable workflow backed by Postgres ([ADR-0006](adr/0006-durable-workflows-on-postgres.md)):

| Workflow | Trigger | Steps |
|---|---|---|
| `post_call` | `call.ended` | finalise transcript → upload recording → LLM extraction → write outcome → enqueue outbox rows → evaluate follow-up rules |
| `outbox_dispatch` | outbox row | call connector with idempotency key → retry with backoff → dead-letter after N tries |
| `campaign_tick` | schedule | pick due contacts → check DNC, consent, calling window, concurrency → place calls |
| `follow_up` | rule match | wait (e.g. 10 min) → send template, or schedule a callback attempt |
| `sim_run` | API / CI | run scenarios → score → store report |

### 3.5 Connectors and tools

A connector is a Python package implementing one or more provider protocols. Packages are discovered via entry points (`ringbridge.connectors`), so third parties can ship `pip install ringbridge-connector-zoho` without forking ([ADR-0007](adr/0007-connector-sdk-and-tools.md)).

```python
class CalendarProvider(Protocol):
    async def availability(self, q: AvailabilityQuery) -> list[Slot]: ...
    async def book(self, req: BookingRequest, idem_key: str) -> Booking: ...
    async def reschedule(self, booking_id: str, slot: Slot, idem_key: str) -> Booking: ...
    async def cancel(self, booking_id: str, idem_key: str) -> None: ...


class CRMProvider(Protocol):
    async def find_contact(self, phone: E164) -> Contact | None: ...
    async def upsert_contact(self, c: ContactUpsert, idem_key: str) -> Contact: ...
    async def log_call(self, contact_id: str, call: CallRecord, idem_key: str) -> None: ...
    async def set_lead_status(self, contact_id: str, status: LeadStatus, idem_key: str) -> None: ...


class MessagingProvider(Protocol):
    channels: set[Channel]  # sms, whatsapp, email

    async def send(self, msg: OutboundMessage, idem_key: str) -> MessageReceipt: ...
```

| Category | v0.1 | Later |
|---|---|---|
| Calendar | Google Calendar, Cal.com | Microsoft 365 / Outlook, Calendly |
| CRM | HubSpot, generic webhook | Zoho CRM, Pipedrive, Salesforce, GoHighLevel |
| Messaging | Twilio SMS, email (SMTP / Resend) | WhatsApp Business Cloud API, Plivo/MSG91 SMS (India, DLT) |
| Tools | HTTP webhook tools (JSON Schema) | MCP servers (streamable HTTP) |

Side effects never go straight from the agent to a third party, with one exception: tools that must answer mid-call (availability, booking) call the connector synchronously with an idempotency key. Everything else goes through the **outbox** ([ADR-0010](adr/0010-outbox-for-side-effects.md)).

### 3.6 Simulation and evals: `ringbridge-sim`

See §7.

### 3.7 Dashboard (M4)

Next.js + shadcn/ui, a thin client over the public API: agent editor (YAML + form view), version publish, numbers, campaigns, a call explorer (audio, transcript, tool calls, per-turn latency trace), and simulation reports. Backend-first: everything the dashboard does is also possible via API and CLI.

### 3.8 CLI: `ringbridge`

`ringbridge init`, `agent validate|publish`, `sim run`, `call test <number>`, `numbers attach`, `connectors list`. Used by humans and CI.

## 4. Agent model: AgentSpec

An agent is a **versioned, declarative spec** (YAML or JSON, validated by a JSON Schema generated from Pydantic models). Published versions are immutable. Numbers and campaigns point at a version, so changes roll out deliberately and roll back instantly ([ADR-0005](adr/0005-declarative-agent-spec.md)).

The core idea: **a small state graph for what must be reliable, free LLM conversation inside each node.**

```yaml
apiVersion: ringbridge.dev/v1alpha1
kind: Agent
metadata: { name: smile-dental-receptionist }
spec:
  language: { default: en-IN, allowed: [en-IN, hi-IN], detect: true }
  voice:
    stt: { provider: deepgram, model: nova-3 }
    llm: { provider: openai, model: gpt-4.1-mini, temperature: 0.3 }
    tts: { provider: cartesia, voice: "<voice-id>" }
    overrides:
      hi-IN: { stt: { provider: sarvam }, tts: { provider: sarvam } }
  persona: |
    You are Asha, the front desk at Smile Dental, Kochi. Warm, brief, never more than two sentences.
  disclosures:
    greeting: "Hi, this is Asha, Smile Dental's AI assistant. This call is recorded."
  business:
    timezone: Asia/Kolkata
    hours: { mon-sat: "09:00-19:00" }
    knowledge: [./kb/services.md, ./kb/faq.md]
  graph:
    start: triage
    nodes:
      triage:
        goal: Find out why they are calling.
        transitions:
          - { to: booking, when: "caller wants a new appointment" }
          - { to: reschedule, when: "caller wants to move or cancel" }
          - { to: handoff, when: "caller asks for a person or it's an emergency" }
      booking:
        goal: Collect details and book a slot.
        collect:                       # typed slots, validated before leaving the node
          name: { type: string }
          reason: { type: enum, values: [cleaning, pain, checkup, other] }
          preferred_time: { type: datetime_window }
        tools: [calendar.availability, calendar.book]
        guardrails:
          - confirm_before: calendar.book   # agent must read back and get an explicit yes
        transitions:
          - { to: wrap_up, when: booked }
      handoff:
        action: transfer
        transfer: { mode: warm, to: "+91XXXXXXXXXX", brief: true, fallback: take_message }
      wrap_up:
        goal: Confirm next steps and end politely.
        tools: [call.end]
  post_call:
    extract:                            # per-agent outcome schema
      outcome: { type: enum, values: [booked, rescheduled, cancelled, info_only, handoff, no_answer, voicemail] }
      lead_status: { type: enum, values: [new, qualified, unqualified, customer] }
      summary: { type: string, max_words: 80 }
    follow_ups:
      - when: "outcome == 'booked'"
        send: { channel: whatsapp, template: booking_confirmation, fallback: sms }
      - when: "outcome == 'no_answer' and attempt < 3"
        schedule_call: { after: 2h, within_window: true }
```

Runtime rules enforced by the graph engine, not by the prompt:

- A node cannot transition until its `collect` slots validate.
- Tools listed in `confirm_before` require a confirmation turn classified as an explicit yes.
- Only the tools listed for the current node are exposed to the LLM.
- Global intents (ask for a human, opt out of calls, "is this a robot?") are checked on every turn.
- Max-turn and silence timeouts per node, with a defined fallback.

## 5. Key flows

### 5.1 Inbound call

```
Caller ─► SIP trunk ─► LiveKit SIP ─► room created ─► dispatch rule ─► agent worker
worker: GET /internal/calls/{id}/config (spec version, contact lookup by caller ID, consents)
worker: greeting + disclosures ─► graph runs (tools via connectors) ─► caller hangs up
worker: POST call.ended ─► post_call workflow ─► outcome + CRM + follow-ups ─► webhooks
```

### 5.2 Outbound campaign attempt

```
campaign_tick ─► pick contact ─► checks: DNC, consent, local calling window, trunk concurrency
            ─► LiveKit CreateSIPParticipant (dial) ─► agent worker joins the room
worker: answering-machine detection in the first seconds
   human     ─► run graph from the campaign's start node
   voicemail ─► wait for the beep ─► leave the templated message (per attempt policy) ─► hang up
   no answer / busy ─► attempt recorded ─► retry policy schedules the next attempt
```

Answering-machine detection (AMD) is not solved for free. Some carriers offer AMD, but a SIP-bridged call does not get it consistently. v0.2 includes a spike comparing carrier AMD, an in-agent classifier (greeting length, transcript cues, beep detection) and a hybrid.

### 5.3 Warm handoff

The agent tells the caller it is connecting them and places them on hold audio. It dials the human (a second SIP participant), speaks a 1–2 sentence brief (name, reason, what has been done), then bridges the caller and leaves. If the human does not answer within N seconds, it falls back to taking a message and creating a callback task. Cold transfer uses SIP REFER.

### 5.4 Post-call

The transcript is assembled from turn events (the agent's own STT and LLM text, so no second transcription is needed). A stronger model then extracts the outcome schema with structured output. The result is validated against the schema (one repair attempt) and written. Outbox rows are created per connector, follow-up rules are evaluated, and `call.analyzed` fires.

## 6. Latency budget

Target **p50 under 800 ms, p95 under 1300 ms** from the end of caller speech to the first agent audio, on a cascaded pipeline in the same region as the providers.

| Stage | Budget (p50) | Notes |
|---|---|---|
| End-of-turn detection | 200–300 ms | VAD + turn-detector model, tuned per language |
| STT final | 100–150 ms | streaming STT, already running during speech |
| LLM time to first token | 250–350 ms | small fast model on the call, short prompts, prompt caching |
| TTS time to first byte | 100–150 ms | streaming TTS, sentence-chunked |
| Network and telephony | 50–100 ms | colocate workers with providers |

Techniques: stream everything, start TTS on the first clause, preload node prompts, keep tool calls under 300 ms or play a natural filler ("Let me check that…"). Speech-to-speech models are an optional engine ([ADR-0003](adr/0003-cascaded-pipeline-default.md)).

Every stage is a span (§8), so regressions are visible per agent, language and provider.

## 7. Quality: simulation and evals

Testing is what sets Ringbridge apart from the rest of the stack.

1. **Scenario specs** (YAML, in the agent repo): a caller persona plus a goal ("wants a cleaning next Tuesday after 5pm, changes mind to Wednesday, asks if it's a robot"), and **assertions**:
   - deterministic: `tool_called(calendar.book, slot.day == "wed")`, `no_tool_before_confirmation`, `transferred`, `disclosure_spoken`, `max_turns <= 14`;
   - judged: an LLM-graded rubric (polite, concise, did not invent prices), with judge prompts versioned and calibrated against human labels.
2. **Text mode** (fast, CI on every PR): the graph runtime runs with text in and out, against an LLM playing the caller. Connectors use fakes with seeded calendars. Results are a pass rate per scenario over N seeds.
3. **Voice mode** (nightly / pre-release): a simulated caller agent joins the room over WebRTC or SIP with TTS speech, injected noise, accents and interruptions. This measures real latency and the turn-taking behaviour that text mode cannot.
4. **Production scoring:** a sample of real calls is scored with the same rubric. Failures can be turned into new scenarios in one click (later, in the dashboard).

Publishing an agent version can be gated on its scenario suite passing.

## 8. Observability

- **Traces:** OpenTelemetry. One trace per call (`call` → `turn` → `stt`, `llm`, `tts`, `tool`), following the GenAI semantic conventions for LLM spans. Workflows continue the call's trace.
- **Metrics:** voice-to-voice latency histograms, interruption rate, tool error rate, outcome rates, cost per call (provider minutes + tokens), campaign answer, voicemail and booking rates.
- **Logs:** structured JSON with `call_id`, `project_id` and the trace id.
- Local stack: Jaeger. Any OTLP backend works in production.

## 9. Data model (core tables)

```
organizations ─< projects ─< api_keys
projects ─< agents ─< agent_versions (immutable spec JSON, published_at)
projects ─< sip_trunks ─< phone_numbers (→ agent_version for inbound)
projects ─< contacts (E.164 phone, tz, locale) ─< consents, dnc_entries
projects ─< campaigns (→ agent_version, schedule, retry policy) ─< campaign_contacts ─< call_attempts
projects ─< calls (direction, status, from/to, started/ended, cost, trace_id)
calls ─< call_events (turns, tool calls, node transitions; append-only)
calls ─1 call_outcomes (extracted JSON + validated fields)
calls ─< recordings (S3 key, retention_until)
projects ─< connector_installs (provider, encrypted credentials, config)
projects ─< outbox (aggregate, connector, payload, idem_key, status, attempts, next_attempt_at)
projects ─< message_templates (channel, locale, body, provider template id)
projects ─< sim_scenarios ─< sim_runs ─< sim_results
```

Every table has `project_id` and an RLS policy. Credentials are encrypted with envelope encryption: a per-project data key wrapped by a master key from env or KMS.

## 10. Security, privacy and compliance

| Area | Mechanism |
|---|---|
| AI and recording disclosure | Mandatory `disclosures.greeting` per agent; the linter fails if it is missing |
| Consent | `consents` table (channel, source, timestamp, proof); outbound and SMS/WhatsApp require it |
| Do-not-call | Project DNC list; "stop calling me" global intent adds the number automatically |
| Calling windows | Per-campaign windows in the contact's local time zone; hard stop outside them |
| US | TCPA (prior express consent for AI voice calls), two-party recording consent states |
| India | TRAI commercial-communication rules, DLT-registered SMS templates, WhatsApp template approval |
| PII | Optional transcript redaction (Presidio) before storage and before LLM extraction; retention policies per project |
| Secrets | Envelope-encrypted connector credentials; never logged; never sent to the LLM |
| API | Scoped API keys, HMAC-signed webhooks, rate limits, audit log of config changes |
| Prompt injection | Tool access limited per node; tool arguments validated by schema; caller content never becomes instructions |

Ringbridge provides the mechanisms, and each deployer is responsible for their own legal compliance. The docs will say so plainly.

## 11. Multilingual (global English + India)

- Language is set per agent (`default`, `allowed`, optional `detect`). Provider overrides apply per language: e.g. Deepgram + Cartesia for English, Sarvam for Hindi and Malayalam.
- Code-switching (Hinglish, Manglish) is expected. Tested with scenarios in each supported language.
- Templates (SMS, WhatsApp, email, voicemail) are keyed by locale.
- Formatting of times, dates, currency and phone numbers is locale-aware. Spoken output is normalised ("2:30 PM" → "two thirty in the afternoon"; "₹1,500" → "fifteen hundred rupees").
- First Indian languages: **Hindi** (v0.2), then **Malayalam and Tamil** (v0.3), based on provider quality measured by our own eval set.

## 12. Deployment

- **Dev / single-node:** `docker compose up` brings up livekit-server, livekit-sip, redis (required by LiveKit SIP), postgres, minio, ringbridge-server (API + workflow workers), ringbridge-agent, and jaeger.
- **Production:** Helm chart (v1.0). Agent workers scale on active-call count; API and workflow workers scale independently. LiveKit can be self-hosted or LiveKit Cloud.
- **Config:** 12-factor env vars; provider keys per project in encrypted connector installs, or env for single-tenant setups.

## 13. Repository layout

```
ringbridge/
├─ packages/
│  ├─ ringbridge-core/        # AgentSpec models + JSON Schema, domain types, connector protocols
│  ├─ ringbridge-agent/       # LiveKit worker, graph runtime, built-in tools
│  ├─ ringbridge-server/      # FastAPI control plane, workflows, migrations
│  ├─ ringbridge-connectors/  # built-in connectors (google, calcom, hubspot, twilio, email, ...)
│  ├─ ringbridge-sim/         # scenario runner, simulated caller, judges, reports
│  └─ ringbridge-cli/         # `ringbridge` command
├─ apps/dashboard/            # Next.js (M4)
├─ examples/                  # dental clinic (EN + HI), real-estate lead caller, home services
├─ deploy/compose/ deploy/helm/
├─ docs/                      # architecture, ADRs, guides
└─ .github/
```

One `uv` workspace; Python 3.12; ruff, mypy (strict), pytest; conventional commits; squash merges ([ADR-0004](adr/0004-python-uv-monorepo.md)).

## 14. Roadmap

| Milestone | Target | Outcome |
|---|---|---|
| M0 Foundations | 30 Nov 2026 | Monorepo, CI, compose stack, ADRs accepted, LiveKit telephony spike |
| M1 Voice core | 14 Dec 2026 | A phone number answered by an agent from an AgentSpec, with traces and latency metrics |
| M2 Receptionist **v0.1** | 10 Jan 2027 | Booking, CRM sync, SMS/email follow-up, warm handoff, post-call pipeline, text-mode sims in CI |
| M3 Outbound + India **v0.2** | 7 Feb 2027 | Campaigns, AMD + voicemail, retries, DNC and windows, WhatsApp, Hindi |
| M4 Platform **v0.3** | 14 Mar 2027 | Multi-tenant API, dashboard and call explorer, voice-mode sims, more connectors, Malayalam/Tamil |
| M5 **v1.0** | 11 Apr 2027 | Helm, security review, docs site, hosted demo number, benchmarks published |

Tracked in the GitHub Project linked from the README.

## 15. Open questions

- Durable workflow engine: DBOS vs Procrastinate vs a thin custom engine (spike in M0, [ADR-0006](adr/0006-durable-workflows-on-postgres.md)).
- AMD approach (spike in M3).
- Indian telephony: which providers allow SIP origination and termination for AI calls under current TRAI rules, and how numbers get provisioned (research in M3).
- Licence of the dashboard (Apache-2.0 like the rest is the default).
