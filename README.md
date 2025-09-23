<a href="https://livekit.io/">
  <img src="./.github/assets/livekit-mark.png" alt="LiveKit logo" width="100" height="100">
</a>

# LiveKit Agents Starter - Python

A complete starter project for building voice AI apps with [LiveKit Agents for Python](https://github.com/livekit/agents).

The starter project includes:

- A simple voice AI assistant based on the [Voice AI quickstart](https://docs.livekit.io/agents/start/voice-ai/)
- Voice AI pipeline based on [OpenAI](https://docs.livekit.io/agents/integrations/llm/openai/), [Cartesia](https://docs.livekit.io/agents/integrations/tts/cartesia/), and [Deepgram](https://docs.livekit.io/agents/integrations/llm/deepgram/)
  - Easily integrate your preferred [LLM](https://docs.livekit.io/agents/integrations/llm/), [STT](https://docs.livekit.io/agents/integrations/stt/), and [TTS](https://docs.livekit.io/agents/integrations/tts/) instead, or swap to a realtime model like the [OpenAI Realtime API](https://docs.livekit.io/agents/integrations/realtime/openai)
- Eval suite based on the LiveKit Agents [testing & evaluation framework](https://docs.livekit.io/agents/build/testing/)
- [LiveKit Turn Detector](https://docs.livekit.io/agents/build/turns/turn-detector/) for contextually-aware speaker detection, with multilingual support
- [LiveKit Cloud enhanced noise cancellation](https://docs.livekit.io/home/cloud/noise-cancellation/)
- Integrated [metrics and logging](https://docs.livekit.io/agents/build/metrics/)

This starter app is compatible with any [custom web/mobile frontend](https://docs.livekit.io/agents/start/frontend/) or [SIP-based telephony](https://docs.livekit.io/agents/start/telephony/).

## Dev Setup

Clone the repository and install dependencies to a virtual environment:

```console
cd agent-starter-python
uv sync
```

Set up the environment by copying `.env.example` to `.env.local` and filling in the required values:

- `LIVEKIT_URL`: Use [LiveKit Cloud](https://cloud.livekit.io/) or [run your own](https://docs.livekit.io/home/self-hosting/)
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`: [Get a key](https://platform.openai.com/api-keys) or use your [preferred LLM provider](https://docs.livekit.io/agents/integrations/llm/)
- `DEEPGRAM_API_KEY`: [Get a key](https://console.deepgram.com/) or use your [preferred STT provider](https://docs.livekit.io/agents/integrations/stt/)
- `CARTESIA_API_KEY`: [Get a key](https://play.cartesia.ai/keys) or use your [preferred TTS provider](https://docs.livekit.io/agents/integrations/tts/)

You can load the LiveKit environment automatically using the [LiveKit CLI](https://docs.livekit.io/home/cli/cli-setup):

```bash
lk app env -w .env.local
```

## Run the agent

Before your first run, you must download certain models such as [Silero VAD](https://docs.livekit.io/agents/build/turns/vad/) and the [LiveKit turn detector](https://docs.livekit.io/agents/build/turns/turn-detector/):

```console
uv run python src/agent.py download-files
```

To run the agent for use with a frontend or telephony, use the `dev` command:

```console
uv run python src/agent.py dev
```

## Run the Livspace agent

Before your first run, you must download certain models such as [Silero VAD](https://docs.livekit.io/agents/build/turns/vad/) and the [LiveKit turn detector](https://docs.livekit.io/agents/build/turns/turn-detector/):

```console
uv run python src/livspace_agent/agent.py download-files
```

To run the agent for use with a frontend or telephony, use the `dev` command:

```console
uv run python src/livspace_agent/agent.py dev
```

## Playground

You can then visit the playground to test out your agent

**Link**: https://agents-playground.livekit.io/#cam=0&mic=1&screen=1&video=0&audio=1&chat=1&theme_color=cyan

## Make Changes to Your Agent

1. **Update Prompt**: Go to ```prompts.py``` and update ```INSTRUCTIONS``` as needed. 
2. **Update LLM**: update the required model string and model provider.
```console
llm=google.LLM(model="gemini-2.5-flash-lite")
``` 
3. **Update TTS**:
```console
tts=elevenlabs.TTS(
      model="eleven_flash_v2_5", 
      voice_id="H8bdWZHK2OgZwTN7ponr",
      voice_settings=elevenlabs.VoiceSettings(
          stability=0.5,
          similarity_boost=0.7,
          speed=1.10,
      ),
      streaming_latency=4
    ),
```
4. **Agent Options**: You can play with a few other agent options to test the agent. You can check if ```preemptive_generation``` helps here.
```console
session = AgentSession(
      vad=ctx.proc.userdata["vad"],
      false_interruption_timeout=1.0,  # Wait 1 second before resuming
      resume_false_interruption=True,   # Enable auto-resume
      # preemptive_generation=True,
    )
```

## Tests and evals

This project includes a complete suite of evals, based on the LiveKit Agents [testing & evaluation framework](https://docs.livekit.io/agents/build/testing/). To run them, use `pytest`.

```console
uv run pytest
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.