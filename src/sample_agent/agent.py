import logging
import os
import yaml

with open("prompts/deepika_agent.yaml") as f:
    data = yaml.safe_load(f)

full_prompt = data["agent_prompt"]

from dotenv import load_dotenv
import json
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    metrics,
    get_job_context,
    AutoSubscribe,
)
from livekit import api
from livekit.agents.llm import function_tool
from livekit.plugins import cartesia, deepgram, noise_cancellation, openai, silero, elevenlabs
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")

load_dotenv(".env.local")


class Assistant(Agent):
    def __init__(self) -> None:
        # __name__ = "my-first-agent"
        super().__init__(
            instructions="""You are a helpful voice AI assistant.
            You eagerly assist users with their questions by providing information from your extensive knowledge.
            Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
            You are curious, friendly, and have a sense of humor.""",
            stt=deepgram.STT(),
            llm=openai.LLM(model="gpt-4o-mini"),
            tts=elevenlabs.TTS(voice_id="H8bdWZHK2OgZwTN7ponr"),
            turn_detection=MultilingualModel(),
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(instructions="Hello, how can I help you today?")

    # all functions annotated with @function_tool will be passed to the LLM when this
    # agent is active
    @function_tool()
    async def lookup_weather(self, context: RunContext, location: str):
        """Use this tool to look up current weather information in the given location.

        If the location is not supported by the weather service, the tool will indicate this. You must tell the user the location's weather is unavailable.

        Args:
            location: The location to look up weather information for (e.g. city name)
        """

        logger.info(f"Looking up weather for {location}")

        return "sunny with a temperature of 70 degrees."
        
    @function_tool
    async def end_call(self, context: RunContext):
        """When you decide to end the call after the end of conversation, use this tool."""

        logger.info("Ending call")
        await context.session.generate_reply(instructions="Thank you for calling. Goodbye!")
        current_speech = context.session.current_speech
        if current_speech is not None:
            await current_speech.wait_for_playout()

        # Stop any active recordings before ending the call
        try:
            job_ctx = get_job_context()
            if job_ctx is not None:
                await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
        except Exception as e:
            logger.error(f"Error during call cleanup: {str(e)}")



def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    req = api.RoomCompositeEgressRequest(
        room_name=ctx.room.name,
        layout="grid",
        audio_only=True,
        file_outputs=[
            api.EncodedFileOutput(
                file_type=api.EncodedFileType.MP4,
                filepath=f"output_{ctx.room.name}.mp4",
                s3=api.S3Upload(
                    access_key=os.getenv("AWS_ACCESS_KEY_ID"),
                    secret=os.getenv("AWS_SECRET_ACCESS_KEY"),
                    bucket=os.getenv("S3_RECORDING_BUCKET"),
                    region=os.getenv("S3_RECORDING_REGION"),   # pick your S3 bucket region
                ),
            ),
        ],
    )

    # await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Set up a voice AI pipeline using OpenAI, Cartesia, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    async def write_transcript():
        filename = f"transcript_{ctx.room.name}.json"
        with open(filename, 'w') as f:
            json.dump(session.history.to_dict(), f, indent=2)

    # sometimes background noise could interrupt the agent session, these are considered false positive interruptions
    # when it's detected, you may resume the agent's speech
    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)

    # Metrics collection, to measure pipeline performance
    # For more information, see https://docs.livekit.io/agents/build/metrics/
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def write_usage():
        summary = usage_collector.get_summary()
        filename = f"usage_{ctx.room.name}.json"
        with open(filename, 'w') as f:
            json.dump(summary.__dict__, f, indent=2)

    ctx.add_shutdown_callback(write_usage)
    ctx.add_shutdown_callback(write_transcript)

    lkapi = api.LiveKitAPI()
    res = await lkapi.egress.start_room_composite_egress(req)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # LiveKit Cloud enhanced noise cancellation
            # - If self-hosting, omit this parameter
            # - For telephony applications, use `BVCTelephony` for best results
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    # Join the room and connect to the user
    await ctx.connect()
    await lkapi.aclose()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
