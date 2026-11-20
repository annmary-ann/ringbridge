#!/usr/bin/env bash
# Smoke-test the local dev stack started with `docker compose up -d --wait`.
# Checks that each service works, not only that it is running.
# Pass --sip to also check the LiveKit SIP bridge (started with the "sip" profile).
set -euo pipefail

NET=ringbridge_default
LK_KEY=devkey
LK_SECRET=devsecret-devsecret-devsecret-devsecret
LK_CLI=livekit/livekit-cli:v2.20.1
AWS_CLI=amazon/aws-cli:2.27.0
export MSYS_NO_PATHCONV=1 # Git Bash on Windows: don't rewrite container paths

pass() { printf '  \033[32mok\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }
lk() { docker run --rm --network "$NET" "$LK_CLI" "$@" --url http://livekit:7880 --api-key "$LK_KEY" --api-secret "$LK_SECRET"; }

echo "Ringbridge dev stack smoke test"

# Redis
[ "$(docker compose exec -T redis redis-cli ping)" = "PONG" ] && pass "redis answers PING" || fail "redis"

# Postgres
docker compose exec -T postgres psql -U ringbridge -d ringbridge -tAc "select 1" | grep -qx 1 \
  && pass "postgres accepts queries" || fail "postgres"

# LiveKit: authenticated API calls (create, list, delete a room)
ROOM="smoke-$RANDOM"
lk room create "$ROOM" >/dev/null && lk room list | grep -q "$ROOM" \
  && pass "livekit API creates and lists rooms" || fail "livekit room API"
lk room delete "$ROOM" >/dev/null 2>&1 || true
docker compose logs livekit 2>&1 | grep -qi "redis" \
  && pass "livekit is using redis" || fail "livekit did not connect to redis"

# S3: authenticated bucket + object round trip
s3() {
  docker run --rm --network "$NET" -e AWS_ACCESS_KEY_ID=ringbridge -e AWS_SECRET_ACCESS_KEY=ringbridge-dev-only \
    -e AWS_DEFAULT_REGION=us-east-1 --entrypoint sh "$AWS_CLI" -c "$1"
}
s3 'aws --endpoint-url http://s3:8333 s3 mb s3://smoke >/dev/null 2>&1 || true;
    echo hello > /tmp/f && aws --endpoint-url http://s3:8333 s3 cp /tmp/f s3://smoke/f >/dev/null &&
    aws --endpoint-url http://s3:8333 s3 cp s3://smoke/f - | grep -qx hello' \
  && pass "s3 stores and returns an object" || fail "s3 round trip"

# Jaeger: OTLP HTTP accepts an (empty) export, and the query API answers
OTLP_PORT="${RINGBRIDGE_OTLP_HTTP_PORT:-4322}"
UI_PORT="${RINGBRIDGE_JAEGER_UI_PORT:-16688}"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d '{"resourceSpans":[]}' "http://localhost:${OTLP_PORT}/v1/traces" || true)
[ "$code" = "200" ] && pass "jaeger accepts OTLP over HTTP" || fail "jaeger OTLP (HTTP $code)"
curl -sf "http://localhost:${UI_PORT}/api/v3/services" >/dev/null && pass "jaeger query API answers" \
  || fail "jaeger query API (Jaeger v2 serves it under /api/v3)"

# LiveKit SIP (optional)
if [ "${1:-}" = "--sip" ]; then
  TRUNK=$(lk sip inbound create --name smoke --numbers "+15550100000" 2>&1 | grep -oE 'ST_[A-Za-z0-9]+' | head -1)
  [ -n "$TRUNK" ] && pass "livekit accepts a SIP inbound trunk ($TRUNK)" || fail "sip inbound trunk"
  lk sip inbound delete "$TRUNK" >/dev/null 2>&1 || true
  docker compose logs sip 2>&1 | grep -qiE "sip.*(listen|start)" \
    && pass "sip bridge is listening" || fail "sip bridge did not start"
fi

echo "All checks passed."
