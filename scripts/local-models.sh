#!/usr/bin/env bash
# Download the free local models Ringbridge uses in development (ADR-0016).
# Works against the `local` Compose profile or your own Ollama / Speaches: set the URLs below.
#
#   uv run poe models                      # the defaults
#   RINGBRIDGE_LOCAL_LLM=qwen2.5:7b uv run poe models
set -euo pipefail

OLLAMA_URL="${RINGBRIDGE_OLLAMA_URL:-http://localhost:11436}"
SPEECH_URL="${RINGBRIDGE_SPEECH_URL:-http://localhost:8089}"
LLM="${RINGBRIDGE_LOCAL_LLM:-qwen2.5:3b}"
STT="${RINGBRIDGE_LOCAL_STT:-Systran/faster-whisper-base}"
TTS="${RINGBRIDGE_LOCAL_TTS:-speaches-ai/piper-en_US-amy-low}"

say() { printf '\033[36m==>\033[0m %s\n' "$1"; }

say "LLM $LLM from $OLLAMA_URL (about 2 GB for the default)"
# Ollama streams progress as JSON lines; keep only status changes.
curl -sfN "$OLLAMA_URL/api/pull" -d "{\"model\":\"$LLM\"}" \
  | grep -o '"status":"[^"]*"' | uniq | sed 's/"status":"\(.*\)"/    \1/'

for model in "$STT" "$TTS"; do
  say "speech model $model from $SPEECH_URL"
  curl -sf -X POST "$SPEECH_URL/v1/models/$model" | sed 's/^/    /'
  echo
done

say "done. Check everything with: uv run poe smoke-local"
