# ADR-0010: Transactional outbox for external side effects

- Status: Accepted
- Date: 2026-11-19

## Context
"Update the CRM and send a WhatsApp after the call" must happen once: never zero times, never twice, even if a worker crashes or a provider times out.

## Decision
Post-call results and their side effects are written in one database transaction: the outcome row plus `outbox` rows (connector, payload, `idem_key`). A dispatcher workflow delivers outbox rows with exponential backoff, passes the idempotency key to the provider (or deduplicates on our side when the provider cannot), and moves rows to dead-letter after N attempts. Webhook delivery to customers uses the same mechanism.

## Consequences
Mid-call tools (availability, booking) are synchronous by necessity. They still pass idempotency keys derived from `call_id + tool_call_id`.
