# ADR-0016: Pluggable speech and LLM providers; zero-cost development

- Status: Accepted
- Date: 2026-11-26

## Context
Ringbridge is a module that businesses run with the models they choose. Some want hosted
APIs (Deepgram, OpenAI, Cartesia, Sarvam), some want everything on their own hardware, and new
providers appear every month. Core cannot hard-code a list.

Development has the same need from the other side. Building and testing Ringbridge must cost
nothing: no paid API keys, no phone numbers, no card-on-file trials. A contributor (the maintainer
included) clones the repo and gets a talking agent on a laptop. CI never needs secrets.

## Decision

**Providers are plug-ins.** `ringbridge-agent` defines three provider kinds (speech-to-text,
LLM and text-to-speech) and finds implementations through the `ringbridge.providers` entry-point
group, the same way connectors work ([ADR-0007](0007-connector-sdk-and-tools.md)). A provider is
a factory:

```python
class ProviderFactory(Protocol):
    kind: Literal["stt", "llm", "tts"]
    id: str  # what `provider:` names in an AgentSpec

    def options_schema(self) -> dict: ...  # JSON Schema for `options`, checked at publish time
    def create(self, ref: ProviderRef, secrets: SecretSource) -> STT | LLM | TTS: ...
```

`create` returns a LiveKit Agents component ([ADR-0002](0002-livekit-agents-runtime.md)), so any
provider with a LiveKit plugin needs only a thin factory. A third party ships
`pip install ringbridge-provider-foo` without forking.

**Built-in providers, in order of priority:**

1. `openai-compatible` for LLM, STT and TTS, with a configurable `base_url`. This one adapter covers
   Ollama, vLLM, LM Studio, llama.cpp server, Groq, Together, OpenRouter, Gemini's OpenAI endpoint
   and OpenAI itself, plus local speech servers that expose the OpenAI audio API.
2. Local defaults that run free on a laptop: Ollama for the LLM, faster-whisper for STT, and
   Piper or Kokoro for TTS. They are served by containers in a `local` Compose profile, reached
   through the `openai-compatible` adapter where the server speaks that API.
3. Fakes for tests: scripted transcripts, canned LLM replies and tool calls, and generated tones
   for audio. They make every pipeline test deterministic and free.
4. Hosted providers (Deepgram, Cartesia, ElevenLabs, Anthropic, Sarvam, ...) as optional extras
   (`ringbridge-agent[deepgram]`), contributed and tested by people who use them.

**Secrets never appear in an AgentSpec.** A spec names a provider and its options. Keys come from
the environment (for example `RINGBRIDGE_PROVIDER_DEEPGRAM_API_KEY`) or, with multi-tenancy, from
per-project encrypted credentials. The publish endpoint rejects a spec that names a provider
the deployment does not have installed.

**Calls without a phone number.** Development calls use the browser (WebRTC into a LiveKit room)
or a free SIP softphone (Linphone, MicroSIP) registered against the local LiveKit SIP bridge.
Calls over the public phone network need the user's own SIP trunk
([ADR-0008](0008-telephony-byo-sip-trunk.md)). That path is documented per provider but is
never needed to develop or test Ringbridge.

## Alternatives considered
- **Hard-code a provider list in the agent package.** Simple, but every new provider becomes a
  core release, and it pushes the project toward whichever APIs the maintainer pays for.
- **Develop against free tiers of hosted APIs.** Trials expire, need cards, and differ by country;
  CI would need secrets, and forks could not run it.
- **Only local models.** Free, but businesses running real call volume will want hosted
  providers, and Indian languages are still better served by some hosted models.

## Consequences
- The development stack gets a `local` profile (Ollama and a local speech server), sized to run
  on a laptop CPU. The first pull downloads several GB of models.
- Local models on a laptop are slower than hosted APIs. Latency reports (#15) separate
  Ringbridge's own overhead (measured with fakes, reproducible anywhere) from end-to-end numbers
  for a named hardware and provider setup.
- The spec validator learns about installed providers and their option schemas at publish
  time, while `ringbridge agent validate` stays offline and checks structure only.
- Each provider package must pass a shared contract test suite against fakes or a local server.
- #5 proves telephony through the browser and a softphone into LiveKit SIP. A real PSTN call
  is a documented, optional step for users who bring a trunk.
