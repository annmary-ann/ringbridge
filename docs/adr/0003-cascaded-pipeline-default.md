# ADR-0003: Cascaded STT → LLM → TTS by default; speech-to-speech optional

- Status: Accepted
- Date: 2026-11-19

## Context
Speech-to-speech (realtime) models sound natural and have low latency, but they limit provider choice, are harder to control with tools and guardrails, cost more per minute, and support Indian languages unevenly. Cascaded pipelines are fully provider-neutral, give us text at every step for guardrails, transcripts and evals, and let us pick the best STT/TTS per language.

## Decision
The default engine is cascaded. Speech-to-speech is a second engine selectable per agent (`voice.engine: realtime`), with the same graph semantics where the provider supports tools.

## Consequences
We must engineer latency carefully (streaming everywhere, sentence-chunked TTS, prompt caching). Latency is measured per stage from M1 onward.
