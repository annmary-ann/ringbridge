# ADR-0013: Compliance mechanisms are product features

- Status: Accepted
- Date: 2026-11-19

## Context
AI voice calling is regulated: TCPA and the FCC's 2024 ruling that AI-generated voices are "artificial" (US), two-party recording consent states, and TRAI commercial-communication and DLT rules (India), plus WhatsApp template policy. Projects that ignore this get their users fined and their numbers blocked.

## Decision
Built in and on by default: AI and recording disclosure in the greeting (linted), consent records with proof, a DNC list with automatic opt-out from the "stop calling" intent, calling windows in the contact's time zone, per-trunk concurrency limits, recording retention, and optional PII redaction.

## Consequences
Some features can only be turned off explicitly, with a config flag named for what it does (e.g. `unsafe_disable_disclosure`). Docs state that operators remain responsible for legal compliance.
