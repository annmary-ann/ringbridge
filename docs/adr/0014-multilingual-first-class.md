# ADR-0014: Multilingual from the start (global English + Indian languages)

- Status: Accepted
- Date: 2026-11-19

## Context
Most voice-agent tooling is English-first. Indian businesses need Hindi and regional languages, and callers switch languages mid-sentence (Hinglish, Manglish).

## Decision
- `spec.language` (`default`, `allowed`, `detect`), with per-language provider overrides (e.g. Sarvam for Indian languages).
- Locale-keyed templates; locale-aware spoken normalisation of times, currency and numbers.
- Our own small eval set per language (STT word error on domain terms, TTS naturalness rating, end-to-end scenario pass rate) decides which provider is the default.
- Order: English (v0.1), Hindi (v0.2), Malayalam and Tamil (v0.3).

## Consequences
Every example agent has at least an English and a Hindi scenario suite from v0.2.
