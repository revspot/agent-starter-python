import logging
import os
from typing import Literal, Optional

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
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    metrics,
    get_job_context,
)
from livekit import api

from livekit.agents.llm import function_tool
from livekit.plugins import cartesia, deepgram, noise_cancellation, openai, silero, elevenlabs, google
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from constants import MASTER_INSTRUCTIONS
from projectagent import ProjectAgent
from newprojectagent import NewProjectAgent

logger = logging.getLogger("livspace-agent")

load_dotenv(".env.local")


class LivspaceAgent(Agent):
    def __init__(self, chat_ctx=None) -> None:

        super().__init__(
            instructions=MASTER_INSTRUCTIONS,
            stt=deepgram.STT(),
            llm=google.LLM(model="gemini-2.5-flash-lite"),
            tts=elevenlabs.TTS(voice_id="H8bdWZHK2OgZwTN7ponr"),
            turn_detection=MultilingualModel(),
            chat_ctx=chat_ctx,
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(instructions=MASTER_INSTRUCTIONS)

    # all functions annotated with @function_tool will be passed to the LLM when this
    # agent is active
    
    @function_tool
    async def get_customer_project_details(self, context: RunContext, customer_name: str = "Subham"):
        """Use this tool to lookup the project details for the customer."""
        logger.info(f"Looking up project details for {customer_name}")
        return f"Thank you, {customer_name}. I have your project details. I am now connecting you to our Project Support team who can best assist you with your query. Please stay on the line."

    @function_tool
    async def transfer_to_project_support(self, context: RunContext):
        """Transfer the call to the Project Support team."""
        logger.info("Transferring call to Project Support team")
        return ProjectAgent(chat_ctx=self.chat_ctx)

    @function_tool
    async def transfer_to_new_project_team(self, context: RunContext):
        """Transfer the call to the New Project team."""
        logger.info("Transferring call to New Project team")
        return NewProjectAgent(chat_ctx=self.chat_ctx)
        
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

    # Helper to write event-specific JSON files in the room folder
    def write_event_json(data: dict, filename: str = None):
        if filename is None:
            filename = os.path.join(f"session_events_{ctx.room.name}.jsonl")
        else:
            filename = os.path.join(f"{filename}_{ctx.room.name}.jsonl")
        with open(filename, "a") as f:  # "a" mode for append
            json.dump(data, f)
            f.write("\n")  # Add newline after each JSON object

        return filename

    req = api.RoomCompositeEgressRequest(
        room_name=ctx.room.name,
        layout="grid",
        audio_only=True,
        file_outputs=[
            api.EncodedFileOutput(
                file_type=api.EncodedFileType.MP4,
                filepath=f"{ctx.room.name}/call_recording_{ctx.room.name}.mp4",
                s3=api.S3Upload(
                    access_key=os.getenv("AWS_ACCESS_KEY_ID"),
                    secret=os.getenv("AWS_SECRET_ACCESS_KEY"),
                    bucket=os.getenv("S3_RECORDING_BUCKET"),
                    region=os.getenv("S3_RECORDING_REGION"),   # pick your S3 bucket region
                ),
            ),
        ],
    )



    # Set up a voice AI pipeline using OpenAI, Cartesia, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )



    # sometimes background noise could interrupt the agent session, these are considered false positive interruptions
    # when it's detected, you may resume the agent's speech
    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)
        filename = write_event_json(ev.model_dump())
        logger.info(f"Agent false interruption: {filename}")

    # Metrics collection, to measure pipeline performance
    # For more information, see https://docs.livekit.io/agents/build/metrics/
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)
        filename = write_event_json(ev.model_dump())
        logger.info(f"Metrics collected: {filename}")

    @session.on("speech_created")
    def _on_speech_created(ev: SpeechCreatedEvent):
        filename = write_event_json(ev.model_dump())
        logger.info(f"Speech created: {filename}")

    @session.on("user_state_changed")
    def _on_user_state_changed(ev: UserStateChangedEvent):
        filename = write_event_json(ev.model_dump())
        logger.info(f"User state changed: {filename}")

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev: UserInputTranscribedEvent):
        filename = write_event_json(ev.model_dump())
        logger.info(f"User input transcribed: {filename}")

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev: ConversationItemAddedEvent):
        filename = write_event_json(ev.model_dump())
        logger.info(f"Conversation item added: {filename}")

    @session.on("function_tools_executed")
    def _on_function_tools_executed(ev: FunctionToolsExecutedEvent):
        filename = write_event_json(ev.model_dump())
        logger.info(f"Function tools executed: {filename}")

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: AgentStateChangedEvent):
        filename = write_event_json(ev.model_dump())
        logger.info(f"Agent state changed: {filename}")
    
    @session.on("error")
    def _on_error(ev: ErrorEvent):
        filename = write_event_json(ev.model_dump())
        logger.info(f"Error: {filename}")
    
    @session.on("close")
    def _on_close(ev: CloseEvent):
        filename = write_event_json(ev.model_dump())
        logger.info(f"Close: {filename}")
    


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
            transcript_filename = write_event_json(session.history.to_dict(), "transcript")
            summary = usage_collector.get_summary()
            summary_filename = write_event_json(summary.__dict__, "summary")
            
            # Upload the single JSONL file to the same S3 folder as egress
            jsonl_filename = f"session_events_{ctx.room.name}.jsonl"
            s3_key = f"{ctx.room.name}/{jsonl_filename}"
            
            if os.path.exists(jsonl_filename):
                s3_client.upload_file(jsonl_filename, s3_bucket, s3_key)
                s3_client.upload_file(transcript_filename, s3_bucket, f"{ctx.room.name}/{transcript_filename}")
                s3_client.upload_file(summary_filename, s3_bucket, f"{ctx.room.name}/{summary_filename}")
                logger.info(f"Uploaded events to s3://{s3_bucket}/{s3_key}")
                
                # Delete the local JSONL file after successful upload
                os.remove(jsonl_filename)
                os.remove(transcript_filename)
                os.remove(summary_filename)
                logger.info(f"Deleted local file: {jsonl_filename}")
            else:
                logger.warning(f"JSONL file {jsonl_filename} not found for upload")
                
        except Exception as e:
            logger.error(f"Failed to upload events to S3: {e}")


    ctx.add_shutdown_callback(write_room_events)


    lkapi = api.LiveKitAPI()
    res = await lkapi.egress.start_room_composite_egress(req)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=LivspaceAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # LiveKit Cloud enhanced noise cancellation
            # - If self-hosting, omit this parameter
            # - For telephony applications, use `BVCTelephony` for best results
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )
    await lkapi.aclose()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name="livspace-agent"))
    # cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
