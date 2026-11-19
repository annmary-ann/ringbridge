# ADR-0012: OpenTelemetry for traces and metrics

- Status: Accepted
- Date: 2026-11-19

## Context
Voice agents fail in latency and turn-taking as often as in content. We need per-stage timings for every turn, linked to the call and to post-call processing.

## Decision
OpenTelemetry everywhere. One trace per call: `call` → `turn` → `stt` / `llm` / `tts` / `tool`, using GenAI semantic conventions for LLM spans (model, tokens). Workflows continue the call's trace via stored trace context. Metrics: voice-to-voice latency histograms, interruption rate, tool errors, outcome rates, cost per call. Export over OTLP; Jaeger in the dev stack.

## Consequences
The same span data feeds the call explorer and the latency benchmarks in the docs.
