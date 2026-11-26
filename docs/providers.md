# Speech and LLM providers

An agent needs three models: speech-to-text (STT), an LLM, and text-to-speech (TTS). Ringbridge
lets you choose each one in the agent's YAML ([ADR-0016](adr/0016-pluggable-providers-zero-cost-dev.md)):
free models on your own machine, any OpenAI-compatible API, or a hosted provider you already
pay for. Nothing in Ringbridge needs a paid account.

## Free, on your machine

The `local` Compose profile runs [Ollama](https://ollama.com) for the LLM and
[Speaches](https://github.com/speaches-ai/speaches) for STT (faster-whisper) and TTS (Piper,
Kokoro). Both run on a laptop CPU; no GPU or key is needed.

```sh
uv run poe up-local      # core stack + ollama (port 11436) + speech (port 8089)
uv run poe models        # download the default models, once (about 2 GB)
uv run poe smoke-local   # TTS -> STT round trip and an LLM reply
```

Already run Ollama yourself? Skip the container's copy of the model: set
`RINGBRIDGE_OLLAMA_URL=http://localhost:11434` in `.env` and pull the model there.

### Defaults, and what they cost in time

| Part | Default | Size | Warm time on an 8-core laptop CPU |
|---|---|---|---|
| LLM | `qwen2.5:3b` | 1.9 GB | ~10–15 s for a short reply |
| STT | `Systran/faster-whisper-base` | 145 MB | ~4 s per utterance |
| TTS | `speaches-ai/piper-en_US-amy-low` | 60 MB | ~1.5 s per sentence |

Measured on 26 Nov 2026 with other containers running, so treat the numbers as rough. The first
request after starting is slower while each model loads.

These defaults are chosen to work, not to feel like a real call: a full turn takes several
seconds on a CPU. That is fine for building and testing flows, tools and transcripts. For
natural latency, use a GPU (Ollama and the `-cuda` Speaches images use it automatically) or a
hosted provider. Latency reports separate Ringbridge's own overhead from model time (#15).

### Other free models

Change them with environment variables before `poe models` and `poe smoke-local`, and in your
agent's `voice` section:

| Variable | Try | Why |
|---|---|---|
| `RINGBRIDGE_LOCAL_LLM` | `qwen2.5:7b`, `llama3.1:8b` | Better answers and tool use; slower and more memory |
| | `qwen2.5:1.5b` | Faster; weaker at tools |
| `RINGBRIDGE_LOCAL_STT` | `Systran/faster-whisper-small` | More accurate, ~2–3x slower |
| | `Systran/faster-whisper-base.en` | English only, a little faster |
| | `smcproject/vegam-whisper-medium-ml` | Malayalam |
| `RINGBRIDGE_LOCAL_TTS` | `speaches-ai/Kokoro-82M-v1.0-ONNX-int8` (voice `af_heart`) | More natural voice, ~5x slower on CPU |
| | other `speaches-ai/piper-*` voices | Other accents and languages |

`curl localhost:8089/v1/registry?task=text-to-speech` (or `automatic-speech-recognition`) lists
everything Speaches can download.

## Any OpenAI-compatible API

The `openai-compatible` provider talks to anything that speaks the OpenAI API, with a
`base_url` option. Ollama, vLLM, LM Studio, llama.cpp server, Groq, Together, OpenRouter,
Gemini's OpenAI endpoint and OpenAI itself all work, and so does Speaches for audio:

```yaml
voice:
  stt: { provider: openai-compatible, model: Systran/faster-whisper-base,
         options: { base_url: "http://localhost:8089/v1" } }
  llm: { provider: openai-compatible, model: qwen2.5:3b,
         options: { base_url: "http://localhost:11436/v1" } }
  tts: { provider: openai-compatible, model: speaches-ai/piper-en_US-amy-low, voice: amy,
         options: { base_url: "http://localhost:8089/v1" } }
```

The provider registry that reads this arrives with the agent worker (#10); the shape above is
what it will accept.

## Hosted providers (your own account)

Hosted providers (Deepgram, Cartesia, ElevenLabs, Anthropic, Sarvam, ...) are optional extras,
installed only by people who use them, for example `ringbridge-agent[deepgram]`.

- Keys live in the environment as `RINGBRIDGE_PROVIDER_<ID>_API_KEY` (for example
  `RINGBRIDGE_PROVIDER_DEEPGRAM_API_KEY`), never in agent files. See `.env.example`.
- Each provider's own pricing page is the source of truth for cost. Set spending limits in its
  dashboard before using it in production.
- CI never uses hosted providers or secrets: tests run on fakes.

## Write your own provider

A provider is a Python package that registers a factory under the `ringbridge.providers`
entry point and passes the shared contract tests. The interface is in ADR-0016; the
step-by-step guide comes with the provider registry (#10).
