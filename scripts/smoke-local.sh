#!/usr/bin/env bash
# Smoke-test the free local models: an agent's whole loop without any account.
#   text-to-speech -> speech-to-text round trip, then one LLM reply through the
#   OpenAI-compatible API that Ringbridge's `openai-compatible` provider uses.
set -euo pipefail

OLLAMA_URL="${RINGBRIDGE_OLLAMA_URL:-http://localhost:11436}"
SPEECH_URL="${RINGBRIDGE_SPEECH_URL:-http://localhost:8089}"
LLM="${RINGBRIDGE_LOCAL_LLM:-qwen2.5:3b}"
STT="${RINGBRIDGE_LOCAL_STT:-Systran/faster-whisper-base}"
TTS="${RINGBRIDGE_LOCAL_TTS:-speaches-ai/piper-en_US-amy-low}"
VOICE="${RINGBRIDGE_LOCAL_VOICE:-amy}"

pass() { printf '  \033[32mok\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }
WAV="$(mktemp -t ringbridge-smoke-XXXXXX.wav)"
trap 'rm -f "$WAV"' EXIT

echo "Ringbridge local models smoke test"

curl -sf "$SPEECH_URL/health" >/dev/null && pass "speech server is up ($SPEECH_URL)" \
  || fail "speech server not reachable at $SPEECH_URL: run 'uv run poe up-local'"
curl -sf "$OLLAMA_URL/api/tags" >/dev/null && pass "ollama is up ($OLLAMA_URL)" \
  || fail "ollama not reachable at $OLLAMA_URL: run 'uv run poe up-local' or set RINGBRIDGE_OLLAMA_URL"

PHRASE="Hello, you have reached the front desk."
curl -sf -X POST "$SPEECH_URL/v1/audio/speech" -H 'content-type: application/json' \
  -d "{\"model\":\"$TTS\",\"voice\":\"$VOICE\",\"input\":\"$PHRASE\",\"response_format\":\"wav\"}" \
  -o "$WAV" || fail "text-to-speech with $TTS (run 'uv run poe models' first)"
[ "$(wc -c < "$WAV")" -gt 10000 ] && pass "text-to-speech produced audio ($TTS)" || fail "TTS audio too short"

HEARD="$(curl -sf -X POST "$SPEECH_URL/v1/audio/transcriptions" \
  -F "file=@$WAV" -F "model=$STT" -F language=en)" || fail "speech-to-text with $STT"
echo "$HEARD" | grep -qi "front desk" && pass "speech-to-text heard it back: $HEARD" \
  || fail "speech-to-text returned: $HEARD"

REPLY="$(curl -sf "$OLLAMA_URL/v1/chat/completions" -H 'content-type: application/json' \
  -d "{\"model\":\"$LLM\",\"max_tokens\":20,\"messages\":[{\"role\":\"user\",\"content\":\"Say only: ready\"}]}")" \
  || fail "LLM $LLM did not answer (run 'uv run poe models' first)"
echo "$REPLY" | grep -qi "ready" && pass "LLM answered through the OpenAI-compatible API ($LLM)" \
  || fail "LLM replied: $REPLY"

echo "All local models work."
