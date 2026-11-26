# Local development stack

`compose.yaml` runs everything Ringbridge depends on, on one machine.

```sh
cp .env.example .env      # optional: only needed to change ports or add provider keys
uv run poe up             # core stack, waits until every service is healthy
uv run poe smoke          # checks each service works, not just that it runs
uv run poe up-local       # add free local models (Ollama, Speaches); see docs/providers.md
uv run poe down           # stop (data volumes are kept)
uv run poe reset          # stop and delete data volumes
```

On Windows with Smart App Control, use `uv run python -m poethepoet <task>` (see CONTRIBUTING).

## Services

| Service | Image | Host port(s) | Used for |
|---|---|---|---|
| `livekit` | livekit/livekit-server v1.13 | 7880 (HTTP/WS), 7881/tcp, 7882/udp | Rooms and media for every call |
| `redis` | redis 8.6 | 6385 | LiveKit routing and the LiveKit SIP message bus |
| `postgres` | postgres 16 | 5435 | Control-plane state |
| `s3` | SeaweedFS 4.54 | 8333 | Recordings (any S3-compatible store works; ADR-0015) |
| `jaeger` | Jaeger 2.23 | 16688 (UI), 4321 (OTLP gRPC), 4322 (OTLP HTTP) | Traces |
| `sip` *(profile `sip`)* | livekit/sip v1.25 | 5060 udp+tcp, 10000–10100/udp | SIP calls: a softphone in development, your own trunk later |
| `ollama` *(profile `local`)* | ollama 0.13.5 | 11436 | Free local LLM ([providers](providers.md)) |
| `speech` *(profile `local`)* | Speaches 0.8.3 (CPU) | 8089 | Free local speech-to-text and text-to-speech |

The ports avoid other common local stacks (Postgres 5432–5434, Jaeger 16686–16687, OTLP 4317–4320, Ollama 11434–11435). Change any of them in `.env`.

Dev credentials: LiveKit `devkey` / `devsecret-devsecret-devsecret-devsecret`, Postgres `ringbridge` / `ringbridge`, S3 `ringbridge` / `ringbridge-dev-only`. They are development-only and appear in `.env.example`.

Jaeger UI: http://localhost:16688

## Phone calls in development

Developing Ringbridge needs no phone number and no account ([ADR-0016](adr/0016-pluggable-providers-zero-cost-dev.md)):

- **Browser calls** (WebRTC) work on the core stack, with no telephony at all.
- **SIP calls from a softphone.** `uv run poe up-sip` adds the LiveKit SIP bridge on port 5060.
  A free softphone on the same machine or your local network (Linphone, MicroSIP, Zoiper) calls
  it directly. Nothing has to be reachable from the internet. Register a trunk whose
  `allowed_addresses` include the softphone's address, add a number, and dial it as
  `sip:+914842000123@<this machine's IP>:5060` (see [control plane](control-plane.md)).
  The telephony spike (#5) writes up the exact softphone settings.

**Real phone numbers** need your own SIP trunk ([ADR-0008](adr/0008-telephony-byo-sip-trunk.md)),
and the provider must reach SIP 5060 and RTP 10000–10100/udp. A laptop behind home NAT or Docker
Desktop usually can't be reached, so production runs on a host with a public IP (with
`use_external_ip: true` in `deploy/compose/sip.yaml`) or uses LiveKit Cloud's SIP endpoint.
