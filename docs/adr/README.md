# Architecture decision records

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-livekit-agents-runtime.md) | LiveKit server, SIP and Agents as the media and agent runtime | Accepted (spike to confirm) |
| [0003](0003-cascaded-pipeline-default.md) | Cascaded STT → LLM → TTS by default; speech-to-speech optional | Accepted |
| [0004](0004-python-uv-monorepo.md) | Python monorepo with a uv workspace; FastAPI control plane | Accepted |
| [0005](0005-declarative-agent-spec.md) | Declarative, versioned AgentSpec: state graph + LLM nodes | Accepted |
| [0006](0006-durable-workflows-on-postgres.md) | Durable workflows on Postgres with DBOS Transact | Accepted |
| [0007](0007-connector-sdk-and-tools.md) | Connector SDK via entry points; HTTP and MCP tools | Accepted |
| [0008](0008-telephony-byo-sip-trunk.md) | Bring-your-own SIP trunk | Accepted |
| [0009](0009-multi-tenancy-rls.md) | Multi-tenancy with Postgres row-level security | Accepted |
| [0010](0010-outbox-for-side-effects.md) | Transactional outbox for external side effects | Accepted |
| [0011](0011-license-apache-2.md) | Apache-2.0 licence, DCO | Accepted |
| [0012](0012-observability-otel.md) | OpenTelemetry traces and metrics | Accepted |
| [0013](0013-compliance-as-features.md) | Compliance mechanisms are product features | Accepted |
| [0014](0014-multilingual-first-class.md) | Multilingual from the start | Accepted |
| [0015](0015-object-storage-seaweedfs.md) | S3-compatible object storage; SeaweedFS in the dev stack | Accepted |
| [0016](0016-pluggable-providers-zero-cost-dev.md) | Pluggable speech and LLM providers; zero-cost development | Accepted |

New ADR: copy [`0000-template.md`](0000-template.md), take the next number, open a PR.
