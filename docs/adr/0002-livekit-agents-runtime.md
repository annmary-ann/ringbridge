# ADR-0002: LiveKit (server, SIP, Agents) as the media and agent runtime

- Status: Accepted (to be confirmed by the M0 telephony spike, #5)
- Date: 2026-11-19

## Context
We need real-time audio, telephony (SIP in and out, transfer, DTMF), voice activity and turn detection, interruption handling and pluggable STT/LLM/TTS. Building this ourselves would take most of a year and is not where Ringbridge adds value.

## Decision
Use **LiveKit server + LiveKit SIP** for media and telephony, and the **LiveKit Agents** Python framework for the agent worker. Ringbridge's graph runtime compiles an AgentSpec onto LiveKit Agents' agent and handoff primitives.

## Alternatives considered
- **Retell / Vapi / Bland as the engine.** Fastest to start, but closed, per-minute pricing, not self-hostable. That contradicts the project's purpose. A future adapter could still export AgentSpecs to them.
- **Pipecat.** Excellent open framework with broad provider support and Pipecat Flows. Telephony usually relies on provider WebSocket media streams or a separate SIP setup. LiveKit's own SIP bridge, room model and self-hostable server give us one coherent stack for phone and web calls. Pipecat stays the fallback if LiveKit becomes a blocker.
- **Build on raw Twilio Media Streams.** Ties us to one carrier and makes us own VAD, turn-taking and jitter handling.

## Consequences
- Self-hosters run LiveKit server, LiveKit SIP and Redis. Compose handles this.
- We follow LiveKit Agents' release cadence. Pin versions and keep our graph runtime behind our own interfaces so the dependency can be swapped.
- The M0 spike must prove: inbound SIP → agent, outbound dial, SIP REFER transfer, and measured latency.
