import logging
import os
from typing import Literal
# import time
import boto3
import tempfile
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
    SpeechCreatedEvent,
    UserStateChangedEvent,
    UserInputTranscribedEvent,
    ConversationItemAddedEvent,
    FunctionToolsExecutedEvent,
    AgentStateChangedEvent,
    ErrorEvent,
    CloseEvent,
    # CloseReason,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    metrics,
    get_job_context,
    # AutoSubscribe,
)
from livekit import api
# from livekit import api, rtc
from livekit.agents.llm import function_tool
from livekit.plugins import cartesia, deepgram, noise_cancellation, openai, silero, elevenlabs, google
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
            # llm=openai.LLM(model="gpt-4o-mini"),
            llm=google.LLM(model="gemini-1.5-flash"),
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

    # INSERT_YOUR_CODE
    # EventTypes = Literal[
    #     "user_state_changed",
    #     "agent_state_changed",
    #     "user_input_transcribed",
    #     "conversation_item_added",
    #     "agent_false_interruption",
    #     "function_tools_executed",
    #     "metrics_collected",
    #     "speech_created",
    #     "error",
    #     "close",
    # ]

    # Create a folder with the room name if it doesn't exist
    room_folder = ctx.room.name
    if not os.path.exists(room_folder):
        os.makedirs(room_folder)

    # Create empty JSON files for each event type in EventTypes
    # for event_name in EventTypes.__args__:
    #     filename = os.path.join(room_folder, f"{event_name}.jsonl")
    #     if not os.path.exists(filename):
    #         with open(filename, "w") as f:
    #             json.dump({}, f)

    # Helper to write event-specific JSON files in the room folder
    def write_event_json(data: dict):
        filename = os.path.join(f"{ctx.room.name}.jsonl")
        with open(filename, "a") as f:  # "a" mode for append
            json.dump(data, f)
            f.write("\n")  # Add newline after each JSON object

    req = api.RoomCompositeEgressRequest(
        room_name=ctx.room.name,
        layout="grid",
        audio_only=True,
        file_outputs=[
            api.EncodedFileOutput(
                file_type=api.EncodedFileType.MP4,
                filepath=f"{ctx.room.name}/output_{ctx.room.name}.mp4",
                # filepath=f"output_{ctx.room.name}.mp4",
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

    # async def write_transcript():
    #     write_event_json("transcript", session.history.to_dict())
        # filename = f"transcript_{ctx.room.name}.json"
        # with open(filename, 'w') as f:
        #     json.dump(session.history.to_dict(), f, indent=2)

    # sometimes background noise could interrupt the agent session, these are considered false positive interruptions
    # when it's detected, you may resume the agent's speech
    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)
        write_event_json(ev.model_dump())

    # Metrics collection, to measure pipeline performance
    # For more information, see https://docs.livekit.io/agents/build/metrics/
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)
        write_event_json(ev.model_dump())

    @session.on("speech_created")
    def _on_speech_created(ev: SpeechCreatedEvent):
        write_event_json(ev.model_dump())
        # logger.info(f"Speech created: {ev.speech_handle.id}")

    @session.on("user_state_changed")
    def _on_user_state_changed(ev: UserStateChangedEvent):
        write_event_json(ev.model_dump())
        # logger.info(f"User state changed: {ev.new_state}")

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev: UserInputTranscribedEvent):
        write_event_json(ev.model_dump())
        # logger.info(f"User input transcribed: {ev.transcript}")

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev: ConversationItemAddedEvent):
        write_event_json(ev.model_dump())
        # logger.info(f"Conversation item added: {ev.item}")

    @session.on("function_tools_executed")
    def _on_function_tools_executed(ev: FunctionToolsExecutedEvent):
        write_event_json(ev.model_dump())
        # logger.info(f"Function tools executed: {ev.function_calls}")

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: AgentStateChangedEvent):
        write_event_json(ev.model_dump())
        # logger.info(f"Agent state changed: {ev.new_state}")
    
    @session.on("error")
    def _on_error(ev: ErrorEvent):
        write_event_json(ev.model_dump())
        # logger.info(f"Error: {ev.error}")
    
    @session.on("close")
    def _on_close(ev: CloseEvent):
        write_event_json(ev.model_dump())
        # logger.info(f"Close: {ev.reason}")
    
    # @session.on("agent_false_interruption")
    # def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
    #     write_event_json("agent_false_interruption", ev.model_dump())
    #     # logger.info(f"Agent false interruption: {ev.message}")

    # async def write_usage():
    #     summary = usage_collector.get_summary()
    #     write_event_json("usage", summary.__dict__)
        # filename = f"usage_{ctx.room.name}.json"
        # with open(filename, 'w') as f:
        #     json.dump(summary.__dict__, f, indent=2)

    async def write_room_events():
        s3_bucket = os.getenv("S3_RECORDING_BUCKET")
        s3_region = os.getenv("S3_RECORDING_REGION")
        s3_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        s3_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        try:
            s3_client = boto3.client(
                "s3",
                region_name=s3_region,
                aws_access_key_id=s3_access_key,
                aws_secret_access_key=s3_secret_key,
            )
            
            # Write final transcript and usage data to the single JSONL file
            write_event_json(session.history.to_dict())
            summary = usage_collector.get_summary()
            write_event_json(summary.__dict__)
            
            # Upload the single JSONL file to the same S3 folder as egress
            jsonl_filename = f"{ctx.room.name}.jsonl"
            s3_key = f"{ctx.room.name}/{jsonl_filename}"
            
            if os.path.exists(jsonl_filename):
                s3_client.upload_file(jsonl_filename, s3_bucket, s3_key)
                logger.info(f"Uploaded events to s3://{s3_bucket}/{s3_key}")
                
                # Delete the local JSONL file after successful upload
                os.remove(jsonl_filename)
                logger.info(f"Deleted local file: {jsonl_filename}")
            else:
                logger.warning(f"JSONL file {jsonl_filename} not found for upload")
                
        except Exception as e:
            logger.error(f"Failed to upload events to S3: {e}")


    # ctx.add_shutdown_callback(write_usage)
    # ctx.add_shutdown_callback(write_transcript)
    ctx.add_shutdown_callback(write_room_events)


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
