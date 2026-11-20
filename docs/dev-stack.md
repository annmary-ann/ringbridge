# Local development stack

`compose.yaml` runs everything Ringbridge depends on, on one machine.

```sh
cp .env.example .env      # optional: only needed to change ports or add provider keys
uv run poe up             # core stack, waits until every service is healthy
uv run poe smoke          # checks each service works, not just that it runs
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
| `sip` *(profile `sip`)* | livekit/sip v1.25 | 5060 udp+tcp, 10000–10100/udp | Phone calls over SIP trunks |

The ports avoid other common local stacks (Postgres 5432–5434, Jaeger 16686–16687, OTLP 4317–4320). Change any of them in `.env`.

Dev credentials: LiveKit `devkey` / `devsecret-devsecret-devsecret-devsecret`, Postgres `ringbridge` / `ringbridge`, S3 `ringbridge` / `ringbridge-dev-only`. They are development-only and appear in `.env.example`.

Jaeger UI: http://localhost:16688

## Phone calls in development

`uv run poe up-sip` adds the LiveKit SIP bridge. A SIP trunk provider (Twilio, Telnyx, ...) can only reach it if **SIP 5060 and the RTP range 10000–10100/udp are reachable from the internet**. A laptop behind home NAT, or Docker Desktop, usually isn't.

Options, in order of simplicity:

1. **LiveKit Cloud for telephony during development.** Point `LIVEKIT_URL`/keys at a free LiveKit Cloud project and use its SIP endpoint. The agent worker still runs locally.
2. **A small cloud VM** with a public IP running this compose file (with `use_external_ip: true` in `deploy/compose/sip.yaml`).
3. **Port forwarding** on your router to this machine. Fiddly, not recommended.

The telephony spike (#5) records which option works best, and the latency of each.

Browser calls (WebRTC) work fully on the local stack with no telephony.
