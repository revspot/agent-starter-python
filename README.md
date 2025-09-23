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
uv run python src/livspace/agent.py download-files
```

Next, run this command to speak to your agent directly in your terminal:

```console
uv run python src/livspace/agent.py console
```

To run the agent for use with a frontend or telephony, use the `dev` command:

```console
uv run python src/livspace/agent.py dev
```

In production, use the `start` command:

```console
uv run python src/livspace/agent.py start
```

## Frontend & Telephony

Get started quickly with our pre-built frontend starter apps, or add telephony support:

| Platform | Link | Description |
|----------|----------|-------------|
| **Web** | [`livekit-examples/agent-starter-react`](https://github.com/livekit-examples/agent-starter-react) | Web voice AI assistant with React & Next.js |
| **iOS/macOS** | [`livekit-examples/agent-starter-swift`](https://github.com/livekit-examples/agent-starter-swift) | Native iOS, macOS, and visionOS voice AI assistant |
| **Flutter** | [`livekit-examples/agent-starter-flutter`](https://github.com/livekit-examples/agent-starter-flutter) | Cross-platform voice AI assistant app |
| **React Native** | [`livekit-examples/voice-assistant-react-native`](https://github.com/livekit-examples/voice-assistant-react-native) | Native mobile app with React Native & Expo |
| **Android** | [`livekit-examples/agent-starter-android`](https://github.com/livekit-examples/agent-starter-android) | Native Android app with Kotlin & Jetpack Compose |
| **Web Embed** | [`livekit-examples/agent-starter-embed`](https://github.com/livekit-examples/agent-starter-embed) | Voice AI widget for any website |
| **Telephony** | [📚 Documentation](https://docs.livekit.io/agents/start/telephony/) | Add inbound or outbound calling to your agent |

For advanced customization, see the [complete frontend guide](https://docs.livekit.io/agents/start/frontend/).

## Tests and evals

This project includes a complete suite of evals, based on the LiveKit Agents [testing & evaluation framework](https://docs.livekit.io/agents/build/testing/). To run them, use `pytest`.

```console
uv run pytest
```

## Using this template repo for your own project

Once you've started your own project based on this repo, you should:

1. **Check in your `uv.lock`**: This file is currently untracked for the template, but you should commit it to your repository for reproducible builds and proper configuration management. (The same applies to `livekit.toml`, if you run your agents in LiveKit Cloud)

2. **Remove the git tracking test**: Delete the "Check files not tracked in git" step from `.github/workflows/tests.yml` since you'll now want this file to be tracked. These are just there for development purposes in the template repo itself.

3. **Add your own repository secrets**: You must [add secrets](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-what-your-workflow-does/using-secrets-in-github-actions) for `OPENAI_API_KEY` or your other LLM provider so that the tests can run in CI.

## Deploying to production

This project is production-ready and includes a working `Dockerfile`. To deploy it to LiveKit Cloud or another environment, see the [deploying to production](https://docs.livekit.io/agents/ops/deployment/) guide.

### Quickstart
Follow these steps to deploy your first agent to LiveKit Cloud.

### Prerequisites
1. **[LiveKit CLI](https://docs.livekit.io/home/cli/) version 2.5 or later**
2. **A [LiveKit Cloud](https://cloud.livekit.io/) project**
3. **A working agent.**

### [Deploy your Agent](https://docs.livekit.io/agents/ops/deployment/#create)

1. **Navigate to your project directory**:
```console
cd your-agent-project
```
2. **Authenticate with LiveKit Cloud:**:
```console
lk cloud auth
```
This opens a browser window to link your LiveKit Cloud project to the CLI. If you've already authenticated and have linked projects, use ```lk project list``` to list all linked projects. Then, set the default project for agent deployment with ```lk project set-default "<project-name>"```.

3. **Deploy your agent:**:
```console
lk agent create
```
This registers your agent with LiveKit Cloud and assigns a unique ID. The ID is written to a new 
```livekit.toml```
 file along with the associated project and other default configuration. If you don't already have a ```Dockerfile```, the CLI creates one for you.

In case you are creating a new agent in an already existing repository, update the ```Dockerfile``` first.
Make sure the right agent.py files are mentioned in the below commands.
```dockerfile
# Pre-download any ML models or files the agent needs
# This ensures the container is ready to run immediately without downloading
# dependencies at runtime, which improves startup time and reliability
RUN uv run src/master-agent/agent.py download-files

# Run the application using UV
# UV will activate the virtual environment and run the agent.
# The "start" command tells the worker to connect to LiveKit and begin waiting for jobs.
CMD ["uv", "run", "src/master-agent/agent.py", "start"]
```

Next, the CLI uploads your agent code to the LiveKit Cloud build service, builds an image from your Dockerfile, and then deploys it to your LiveKit Cloud project. See the [Builds](https://docs.livekit.io/agents/ops/deployment/builds/) guide for details on the build process, logs, and templates.

Your agent is now deployed to LiveKit Cloud and is ready to handle requests. To connect, use the [Agent Playground](https://docs.livekit.io/agents/start/playground/), [custom frontend](https://docs.livekit.io/agents/start/frontend/), or [telephony integration](https://docs.livekit.io/agents/start/telephony/).

### [Monitor status and logs](https://docs.livekit.io/agents/ops/deployment/#monitor-status-and-logs)

Use the CLI to monitor the [status](https://docs.livekit.io/agents/ops/deployment/cli/#status) and [logs](https://docs.livekit.io/agents/ops/deployment/logs/#logs) of your agent.

1. **Monitor agent status:**:
```console
lk agent status
```
This shows status, replica count, and other details for your running agent.
```console
lk agent status --id <agent_id>
```

2. **Tail agent logs**:
```console
lk agent logs
```
This shows a live tail of the logs for the new instance of your deployed agent.
```console
lk agent logs --id <agent_id>
```
This shows a live tail of the logs for the new instance of your deployed agent for a specific agent based on ```agent_id```.

The ```agent_id``` can be found in the **Livekit Cloud** or using **CLI**:
```console
lk agent list
```

### [Deploying new versions](https://docs.livekit.io/agents/ops/deployment/#deploy)
To deploy a new version of your agent, first update the ```Dockerfile``` and ```livekit.toml``` file.

```dockerfile
# Pre-download any ML models or files the agent needs
# This ensures the container is ready to run immediately without downloading
# dependencies at runtime, which improves startup time and reliability
RUN uv run src/master-agent/agent.py download-files

# Run the application using UV
# UV will activate the virtual environment and run the agent.
# The "start" command tells the worker to connect to LiveKit and begin waiting for jobs.
CMD ["uv", "run", "src/master-agent/agent.py", "start"]
```

```toml
[project]
  subdomain = "test-nj8phhn3" #your current project

[agent]
  id = "<agent_id>"
```

To deploy a new version of your agent, run the following command:
```console
lk agent deploy
```
LiveKit Cloud builds a container image that includes your agent code. The new version is pushed to production using a rolling deployment strategy. The rolling deployment allows new instances to serve new sessions, while existing instances are given up to 1 hour to complete active sessions. This ensures your new version is deployed without user interruptions or service downtime.

When you run ```lk agent deploy```, LiveKit Cloud follows this process:

1. **Build**: The CLI uploads your code and builds a container image from your Dockerfile. See [Builds](https://docs.livekit.io/agents/ops/deployment/builds/) for more information).
2. **Deploy**: New agent instances with your updated code are deployed alongside existing instances.
3. **Route new sessions**: New agent requests are routed to new instances.
4. **Graceful shutdown**: Old instances stop accepting new sessions, while remaining active for up to 1 hour to complete any active sessions.
5. **Autoscale**: New instances are automatically scaled up and down to meet demand.

### [Rolling back](https://docs.livekit.io/agents/ops/deployment/#rolling-back)

You can quickly rollback to a previous version of your agent, without a rebuild, by using the following command:

```console
lk agent rollback
```
Rollback operates in the same rolling manner as a normal deployment.

### Regions
Currently, LiveKit Cloud deploys all agents to ```us-east``` (N. Virginia). More regions are coming soon.

### Dashboard
The LiveKit Cloud dashboard provides a view into the status of your deployed and self-hosted agents.

1. **Realtime metrics**: Monitor session count, agent status, and more.
2. **Error tracking**: Identify and diagnose errors in agent sessions.
3. **Usage and limits**: Track usage, billing, and limits.

```console
Agent Dashboard: https://cloud.livekit.io/projects/p_3poatuj2q0u/agents
```


### Configuration with livekit.toml 
The ```livekit.toml``` file contains your agent's deployment configuration. The CLI automatically looks for this file in the current directory, and uses it when any ```lk agent``` commands are run in that directory.

```toml
[project]
subdomain = "<my-project-subdomain>"

[agent]
id = "<agent-id>"
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.