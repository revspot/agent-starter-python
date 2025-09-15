from __future__ import annotations

import logging
import os
from typing import Any
import asyncio
import aiohttp
import re

import boto3
import datetime
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

from livekit import api, rtc

from livekit.agents.llm import function_tool
from livekit.plugins import openai, deepgram, google, elevenlabs, silero, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from dra_homes_inbound.constants import INSTRUCTIONS

logger = logging.getLogger("dra-homes-inbound-agent")
load_dotenv(".env.local")

def extract_sip_status_from_error(error: Exception) -> dict:
    """
    Extract SIP status information from TwirpError or other SIP-related exceptions.
    
    Returns a dictionary with SIP status details:
    - sip_status_code: The numeric SIP status code (e.g., 486, 503)
    - sip_status_message: The human-readable status message (e.g., "User Busy")
    - error_type: The type of error (e.g., "TwirpError")
    - raw_error: The original error message
    """
    sip_info = {
        "sip_status_code": None,
        "sip_status_message": None,
        "error_type": type(error).__name__,
        "raw_error": str(error)
    }
    
    error_str = str(error)
    
    # Check if it's a TwirpError with SIP status information
    if "TwirpError" in error_str and "sip status" in error_str.lower():
        # Extract SIP status code using regex
        sip_code_match = re.search(r'sip status:\s*(\d+)', error_str)
        if sip_code_match:
            sip_info["sip_status_code"] = int(sip_code_match.group(1))
        
        # Extract SIP status message
        sip_message_match = re.search(r'sip status:\s*\d+:\s*([^,]+)', error_str)
        if sip_message_match:
            sip_info["sip_status_message"] = sip_message_match.group(1).strip()
    
    # Check for metadata with SIP information
    if hasattr(error, 'metadata') and error.metadata:
        metadata = error.metadata
        if 'sip_status' in metadata:
            sip_info["sip_status_message"] = metadata['sip_status']
        if 'sip_status_code' in metadata:
            sip_info["sip_status_code"] = int(metadata['sip_status_code'])
    
    return sip_info

def identify_call_status(error: Exception) -> str:
    """
    Simple function to identify if a SIP call failed due to no-answer or busy status.
    
    Args:
        error: The exception that occurred during SIP participant creation
        
    Returns:
        str: One of the following:
        - "busy" - User is busy (486, 600)
        - "no_answer" - No answer (408, 480, 504, 603, 604)
        - "other" - Other error types
        - "unknown" - Could not determine status
    """
    sip_info = extract_sip_status_from_error(error)
    status_code = sip_info.get('sip_status_code')
    
    if not status_code:
        return "unknown"
    
    # Busy status codes
    if status_code in [486, 600]:
        return "busy"
    
    # No answer status codes
    if status_code in [408, 480, 504, 603, 604]:
        return "no_answer"
    
    # All other status codes
    return "other"

class DraHomesInboundAgent(Agent):
    def __init__(self,
                 customer_name: str,
                 lead_honorific: str,
                 greeting_time: str,
                 salutation: str,
                 chat_ctx=None,
                 dial_info=dict[str, Any]):
        self.__name__ = "livekit_dra_homes_inbound"
        instructions = INSTRUCTIONS.replace("{{lead_honorific}}", lead_honorific)
        super().__init__(
            instructions=instructions,
            stt=elevenlabs.STT(),
            llm=google.LLM(model="gemini-2.5-flash-lite"),
            tts=elevenlabs.TTS(
                model="eleven_flash_v2_5", 
                voice_id="90ipbRoKi4CpHXvKVtl0",
                streaming_latency=4
                ),
            turn_detection=MultilingualModel(),
            chat_ctx=chat_ctx,
        )
        self.dial_info = dial_info
        self.customer_name = customer_name
        self.lead_honorific = lead_honorific
        self.greeting_time = greeting_time
        self.salutation = salutation
        self.participant: rtc.RemoteParticipant | None = None

    async def on_enter(self) -> None:
        await self.session.generate_reply(instructions=f"""Good {self.greeting_time}, am I speaking with {self.salutation} {self.customer_name}?""")

    @function_tool
    async def voice_mail_detection(self, context: RunContext):
        """Detect when a call has been answered by a voicemail system rather than a human.
            Call this function when you detect that the call recipient is not available and the call has been answered by an automated voicemail system.

            Common indicators of voicemail:
            - Automated greeting messages: "You have reached the voicemail of..."
            - Recording instructions: "Please leave a message after the beep/tone"
            - Voicemail system prompts: "Please leave your name and number"
            - Generic unavailable messages: "The number you have dialed is not available"

            Before calling this function:
            - Provide a specific reason referencing the actual voicemail content heard

            After calling this function:
            - If a voicemail message is configured, it will be played automatically
            - The call will end immediately after the message (or immediately if no message)
            - No further conversation will take place

            You must provide a specific reason for detecting voicemail that references the exact wording that indicated voicemail.

            EXAMPLE FLOWS:

            Example 1 (clear voicemail greeting):
            System plays: "Hi, you've reached Sarah. I'm not available right now. Please leave a message after the beep."
            Assistant: [voicemail_detection function called with reason="automated greeting detected: 'Hi, you've reached Sarah. I'm not available right now. Please leave a message after the beep.'"]

            Example 2 (generic voicemail):
            System plays: "The number you have dialed is not available. At the tone, please leave a message."
            Assistant: [voicemail_detection function called with reason="voicemail instruction detected: 'The number you have dialed is not available. At the tone, please leave a message.'"]

            Example 3 (DO NOT call - human response):
            Human: "Hello? Who is this?"
            Assistant: [follows system prompt and conversation objectives rather than calling voicemail_detection]

            You must provide a specific reason for detecting voicemail. Never call this tool without a valid reason.
            The reason must include a specific reference to the wording in the user message that indicates voicemail."""

        logger.info(f"voice mail detection function called")

        self._closing_task = asyncio.create_task(self.session.aclose())
        # try:
        #     job_ctx = get_job_context()
        #     if job_ctx is not None:
        #         await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
        # except Exception as e:
        #     logger.error(f"Error during call cleanup: {str(e)}")

    @function_tool
    async def end_call(self, context: RunContext):
        """Gracefully conclude conversations when appropriate
            Call this function when:
            1. EXPLICIT ENDINGS
            - User says goodbye variants: "bye," "see you," "that's all," etc.
            - User directly declines help: "no thanks," "I'm good," etc.
            - User indicates completion: "that's what I needed," "all set," etc.

            2. IMPLICIT ENDINGS
            - User gives minimal/disengaged responses after their needs are met
            - User expresses intention to leave: "I need to go," "getting late," etc.
            - Natural conversation conclusion after all queries are resolved

            Before calling this function:
            1. Confirm all user queries are fully addressed
            2. Provide a contextually appropriate closing response:
            - For task completion: "Glad I could help with [specific task]! Have a great day!"
            - For general endings: "Thanks for chatting! Take care!"
            - For business contexts: "Thank you for your business! Don't hesitate to reach out again."

            DO NOT:
            - Call this function when you have asked a question and waiting for an answer from the user
            - Call this function during active problem-solving
            - End conversation when user expresses new concerns
            - Use generic closings without acknowledging the specific interaction
            - Continue conversation after user has clearly indicated ending
            - Add "Let me know if you need anything else" after user says goodbye

            Example Flow:
            User: "That's all I needed, thanks!"
            Assistant: "Happy I could help with your password reset! Have a wonderful day!"
            [end_call function called]"""

        logger.info("end_call function called")
        await context.session.generate_reply(instructions="Thank you for calling. Goodbye!", allow_interruptions=True)
        current_speech = context.session.current_speech
        if current_speech is not None:
            await current_speech.wait_for_playout()

        self._closing_task = asyncio.create_task(self.session.aclose())
        # try:
        #     job_ctx = get_job_context()
        #     if job_ctx is not None:
        #         await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
        # except Exception as e:
        #     logger.error(f"Error during call cleanup: {str(e)}")

    def set_participant(self, participant: rtc.RemoteParticipant):
        self.participant = participant

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def send_webhook_to_qualif(data: dict, url: str):
    """Send webhook to Qualif"""
    logger.info(f"Sending webhook to {url}")
    async with aiohttp.ClientSession() as http_session:
        async with http_session.post(url, json=data) as response:
            if response.status == 200 or response.status == 201:
                logger.info(f"Webhook sent successfully to {url}, Response: {response.status}")
            else:
                logger.error(f"Failed to send webhook: {response.status}")
                error_message = await response.text()
                logger.error(f"Error message: {error_message}")
                raise Exception(f"Webhook failed with status {response.status}: {error_message}")


async def entrypoint(ctx: JobContext):
    """Entrypoint for the agent"""
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect()
    room_id = await ctx.room.sid
    logger.info(f"connected to room {ctx.room.name}, room_id: {room_id}")

    dial_info = json.loads(ctx.job.metadata)
    bridge_id = dial_info.get("bridge_id")
    trunk_id = dial_info.get("trunk_id")
    participant_identity = dial_info.get("phone_number")
    phone_number = dial_info.get("phone_number")
    logger.info(f"sip_trunk_id : {trunk_id}")
    # dynamic_vars = dial_info.get("dynamic_vars")
    # customer_name = dial_info.get("customer_name")
    customer_name = dial_info.get("dynamic_vars", {}).get("customer_name")
    lead_honorific = dial_info.get("dynamic_vars", {}).get("lead_honorific")
    greeting_time = dial_info.get("dynamic_vars", {}).get("greeting_time")
    salutation = dial_info.get("dynamic_vars", {}).get("salutation")
    logger.info(f"Phone number: {phone_number}, Customer name: {customer_name}, Lead honorific: {lead_honorific}, Greeting time: {greeting_time}, Salutation: {salutation}")

    # Helper to write event-specific JSONL files (one JSON object per line)
    def write_event_jsonl(data: dict, filename: str = None):
        """Write event to JSONL file"""
        if filename is None:
            filename = os.path.join(f"session_events_{ctx.room.name}.jsonl")
        else:
            filename = os.path.join(f"{filename}_{ctx.room.name}.jsonl")
        with open(filename, "a") as f:  # "a" mode for append
            json.dump(data, f)
            f.write("\n")  # Add newline after each JSON object
        return filename

    # Helper to write single JSON files (complete JSON object)
    def write_event_json(data: dict, filename: str):
        """Write event to JSON file"""
        filename = os.path.join(f"{filename}_{ctx.room.name}.json")
        with open(filename, "w") as f:  # "w" mode to overwrite
            json.dump(data, f, indent=2)  # Pretty print for readability
        return filename

    req = api.RoomCompositeEgressRequest(
        room_name=ctx.room.name,
        layout="grid",
        audio_only=True,
        file_outputs=[
            api.EncodedFileOutput(
                file_type=api.EncodedFileType.MP4,
                filepath=f"dra_homes_inbound/{ctx.room.name}/call_recording_{ctx.room.name}.mp4",
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
        false_interruption_timeout=1.0,  # Wait 1 second before resuming
        resume_false_interruption=True,   # Enable auto-resume
        preemptive_generation=True,
        # allow_interruptions=True,
        # min_interruption_duration=0.5,
        # min_interruption_words=2
    )

    # sometimes background noise could interrupt the agent session, these are considered false positive interruptions
    # when it's detected, you may resume the agent's speech
    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN, allow_interruptions=True)
        filename = write_event_jsonl(ev.model_dump())
        logger.info(f"Agent false interruption: {filename}")

    # Metrics collection, to measure pipeline performance
    # For more information, see https://docs.livekit.io/agents/build/metrics/
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)
        filename = write_event_jsonl(ev.model_dump())
        logger.info(f"Metrics collected: {filename}")

    @session.on("speech_created")
    def _on_speech_created(ev: SpeechCreatedEvent):
        filename = write_event_jsonl(ev.model_dump())
        logger.info(f"Speech created: {filename}")

    @session.on("user_state_changed")
    def _on_user_state_changed(ev: UserStateChangedEvent):
        filename = write_event_jsonl(ev.model_dump())
        logger.info(f"User state changed: {filename}")

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(ev: UserInputTranscribedEvent):
        filename = write_event_jsonl(ev.model_dump())
        logger.info(f"User input transcribed: {filename}")

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev: ConversationItemAddedEvent):
        filename = write_event_jsonl(ev.model_dump())
        logger.info(f"Conversation item added: {filename}")

    @session.on("function_tools_executed")
    def _on_function_tools_executed(ev: FunctionToolsExecutedEvent):
        filename = write_event_jsonl(ev.model_dump())
        data = ev.model_dump()
        data["event"] = "function_tools_executed"
        data["room"] = {"sid": room_id}
        url = f"https://qualif.revspot.ai/livekit/events"
        asyncio.create_task(send_webhook_to_qualif(data, url))
        logger.info(f"Function tools executed: {filename}")

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: AgentStateChangedEvent):
        filename = write_event_jsonl(ev.model_dump())
        logger.info(f"Agent state changed: {filename}")
    
    @session.on("error")
    def _on_error(ev: ErrorEvent):
        filename = write_event_jsonl(ev.model_dump())
        logger.info(f"Error: {filename}")
    
    @session.on("close")
    def _on_close(ev: CloseEvent):
        filename = write_event_jsonl(ev.model_dump())
        logger.info(f"Close: {filename}")
        data = ev.model_dump()
        data["event"] = "session_closed"
        data["room"] = {"sid": room_id}
        url = f"https://qualif.revspot.ai/livekit/events"
        asyncio.create_task(send_webhook_to_qualif(data, url))
        asyncio.create_task(ctx.delete_room())
        # await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
    


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
            
            # Write final transcript and usage data to the single JSON file
            transcript_filename = write_event_json(session.history.to_dict(), "transcript")
            summary = usage_collector.get_summary()
            summary_filename = write_event_json(summary.__dict__, "summary")
            
            # Upload the single JSONL file to the same S3 folder as egress
            jsonl_filename = f"session_events_{ctx.room.name}.jsonl"
            s3_key = f"dra_homes_inbound/{ctx.room.name}/{jsonl_filename}"

            # with open(f'room_events_{ctx.room.name}.json', 'r') as file:
            #     remote_participant_data = json.load(file)
            #     call_started_ts = remote_participant_data.get("joined_at")
            #     s3_client.upload_file(f'room_events_{ctx.room.name}.json', s3_bucket, f"dra_homes_inbound/{ctx.room.name}/room_events_{ctx.room.name}.json")
            #     os.remove(f'room_events_{ctx.room.name}.json')
            
            if os.path.exists(jsonl_filename):
                s3_client.upload_file(jsonl_filename, s3_bucket, s3_key)
                s3_client.upload_file(transcript_filename, s3_bucket, f"dra_homes_inbound/{ctx.room.name}/{transcript_filename}")
                s3_client.upload_file(summary_filename, s3_bucket, f"dra_homes_inbound/{ctx.room.name}/{summary_filename}")
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

            
        try:
            data = {
                "conversation_id": ctx.room.name,
                "status": "completed",
                "room_id": room_id,
                # "call_started_ts": call_started_ts,
                "recording_url": f"https://{os.getenv('S3_RECORDING_BUCKET')}.s3.{os.getenv('S3_RECORDING_REGION')}.amazonaws.com/dra_homes_inbound/{ctx.room.name}/call_recording_{ctx.room.name}.mp4",
                "transcript": session.history.to_dict(),
                "summary": summary.__dict__
            }

            url = f"https://qualif.revspot.ai/livekit/webhook_listener/{bridge_id}"
            logger.info(f"Sending webhook to {url}")
            
            await send_webhook_to_qualif(data, url)
                
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")


    ctx.add_shutdown_callback(write_room_events)


    lkapi = api.LiveKitAPI()
    res = await lkapi.egress.start_room_composite_egress(req)

    agent = DraHomesInboundAgent(customer_name=customer_name, lead_honorific=lead_honorific, greeting_time=greeting_time, salutation=salutation, dial_info=dial_info)

    # Start the session, which initializes the voice pipeline and warms up the models
    session_started = asyncio.create_task(
        session.start(
            agent=agent,
            room=ctx.room,
            room_input_options=RoomInputOptions(
                # LiveKit Cloud enhanced noise cancellation
                # - If self-hosting, omit this parameter
                # - For telephony applications, use `BVCTelephony` for best results
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
    )
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                # sip_trunk_id=os.getenv("SIP_OUTBOUND_TRUNK_ID"),
                sip_trunk_id=trunk_id,
                sip_call_to=phone_number,
                participant_identity=participant_identity,
                wait_until_answered=True,
            )
        )

        await session_started
        participant = await ctx.wait_for_participant(identity=participant_identity)
        logger.info(f"participant joined: {participant.identity}")

        agent.set_participant(participant)
        await lkapi.aclose()
        
    except Exception as e:
        # Identify the call status (busy, no_answer, other, unknown)
        call_status = identify_call_status(e)
        
        # # Extract SIP status information for detailed logging
        # sip_info = extract_sip_status_from_error(e)
        
        # Log the call status and SIP details
        logger.error(f"Failed to create SIP participant: {e}")
        logger.error(f"Call Status: {call_status}")

        url = f"https://qualif.revspot.ai/livekit/webhook_listener/{bridge_id}"
        logger.info(f"Sending webhook to {url}")

        status_mapping = {
            "in-progress": "processing",
            "completed": "ended",
            "failed": "dial_failed",
            "cancelled": "dial_failed",
            "busy": "dial_busy",
            "no-answer": "dial_no_answer",
            "ringing": "processing",
            "initiated": "processing",
            "error": "error",
        }
        data = {
            "event": "failed_to_create_sip_participant",
            "conversation_id": ctx.room.name,
            "status": status_mapping.get(call_status, "error"),
            "room_id": room_id,
            "call_status": call_status,
            "error": str(e),
        }
        await send_webhook_to_qualif(data, url)

        # logger.error(f"SIP Status Code: {sip_info.get('sip_status_code', 'Unknown')}")
        # logger.error(f"SIP Status Message: {sip_info.get('sip_status_message', 'Unknown')}")
        
        # You can now use call_status to decide your action:
        # - "busy": User is busy, you might want to retry later
        # - "no_answer": No answer, you might want to retry or mark as no answer
        # - "other": Other error, check logs for details
        # - "unknown": Could not determine, check raw error
        
        # logger.error(f"Raw error details: {sip_info.get('raw_error', str(e))}")
        
        ctx.shutdown()
        await lkapi.aclose()
        return


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name="livekit_dra_homes_inbound"))
    # cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
