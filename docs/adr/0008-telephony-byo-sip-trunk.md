# ADR-0008: Telephony is bring-your-own SIP trunk

- Status: Accepted
- Date: 2026-11-19

## Context
Number availability, pricing and regulation differ by country. India in particular restricts how VoIP connects to the PSTN, and needs local providers.

## Decision
Ringbridge never resells numbers. A project registers one or more SIP trunks (Twilio Elastic SIP, Telnyx, Plivo, Exotel, or any SIP provider). Ringbridge configures LiveKit inbound trunks and dispatch rules and outbound trunks via the LiveKit API. Docs include tested setup guides per provider.

## Consequences
Getting started needs one extra setup step, so we ship a 10-minute quickstart for Twilio and Telnyx. For India, an M3 research issue confirms which providers allow AI calling over SIP and what registration is needed.
