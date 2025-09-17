from __future__ import annotations

import logging
import os
from typing import Any
import asyncio
import aiohttp

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
from meragi_inbound.constants import INSTRUCTIONS
from openai.types.beta.realtime.session import TurnDetection as OpenAITurnDetection

logger = logging.getLogger("meragi-inbound-agent")
load_dotenv(".env.local")

class MeragiInboundAgent(Agent):
    def __init__(self,
                 customer_name: str,
                 chat_ctx=None,
                 dial_info=dict[str, Any]):
        self.__name__ = "meragi-inbound-agent"
        instructions = INSTRUCTIONS.replace("{{customer_name}}", customer_name)
        super().__init__(
            instructions=instructions,
            # stt=deepgram.STT(),
            # llm=google.LLM(model="gemini-2.5-flash-lite"),
            # tts=elevenlabs.TTS(voice_id="H8bdWZHK2OgZwTN7ponr"),
            # turn_detection=MultilingualModel(),
            chat_ctx=chat_ctx,
            llm=openai.realtime.RealtimeModel(
                model="gpt-4o-mini-realtime-preview",
                voice="marin",
                temperature=0.8,
                turn_detection=OpenAITurnDetection(
                        type="server_vad",
                        threshold=0.5,
                        prefix_padding_ms=300,
                        silence_duration_ms=500,
                        create_response=True,
                        interrupt_response=True,
                    )
                )
        )
        self.dial_info = dial_info
        self.customer_name = customer_name
        self.participant: rtc.RemoteParticipant | None = None

    async def on_enter(self) -> None:
        self.session.generate_reply(instructions=INSTRUCTIONS.replace("{{customer_name}}", self.customer_name))

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
        try:
            job_ctx = get_job_context()
            if job_ctx is not None:
                await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
        except Exception as e:
            logger.error(f"Error during call cleanup: {str(e)}")

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
        await context.session.generate_reply(instructions="Thank you for calling. Goodbye!")
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

    @function_tool
    async def budget_calculator(self, context: RunContext, city: str, number_of_events: int, pax: int):
        """Use this tool to calculate the budget for the wedding.
        You will need to capture the city, number of events, and pax to calculate the budget."""
        logger.info(f"Calculating budget for {city}, {number_of_events}, {pax}")

        photo_multiplier = 0.6 if city == "Bangalore" else 0.8
        catering_multiplier = 0.005
        decor_multiplier = 0.75

        catering_budget = pax*catering_multiplier
        photo_budget = number_of_events*photo_multiplier
        decor_budget = number_of_events*decor_multiplier
        
        total_budget = catering_budget + photo_budget + decor_budget

        return f"Decor Budget: {decor_budget:.2f} Lakhs, Photo Budget: {photo_budget:.2f} Lakhs, Catering Budget: {catering_budget:.2f} Lakhs, Total Budget: {total_budget:.2f} Lakhs"

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
    participant_identity = dial_info.get("phone_number")
    phone_number = dial_info.get("phone_number")
    customer_name = dial_info.get("customer_name")
    logger.info(f"Phone number: {phone_number}, Customer name: {customer_name}")

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
                filepath=f"meragi_inbound/{ctx.room.name}/call_recording_{ctx.room.name}.mp4",
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
    )

    # @ctx.room.on("participant_connected")
    # def on_participant_connected(participant: rtc.RemoteParticipant):
    #     data = {
    #         "identity": participant.identity,
    #         "sid": participant.sid,
    #         "metadata": participant.metadata,
    #         "joined_at": datetime.datetime.now().isoformat(),
    #         # "joined_at": participant.joined_at.isoformat() if participant.joined_at else None,
    #     }
    #     filename = write_event_json(data, filename = "room_events")
    #     logging.info(f"Participant connected: {participant.identity}")

    # @ctx.room.on("participant_disconnected")
    # def on_participant_disconnected(participant: rtc.RemoteParticipant):
    #     data = {
    #         "identity": participant.identity,
    #         "sid": participant.sid,
    #         "metadata": participant.metadata,
    #         "left_at": datetime.datetime.now().isoformat(),
    #     }
    #     filename = write_event_json(data, filename = "room_events")
    #     logging.info(f"Participant disconnected: {participant.identity}")


    # sometimes background noise could interrupt the agent session, these are considered false positive interruptions
    # when it's detected, you may resume the agent's speech
    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)
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
        url = f"http://localhost:8001/livekit/events"
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
        url = f"http://localhost:8001/livekit/events"
        asyncio.create_task(send_webhook_to_qualif(data, url))
        ctx.delete_room()
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
            s3_key = f"meragi_inbound/{ctx.room.name}/{jsonl_filename}"

            # with open(f'room_events_{ctx.room.name}.json', 'r') as file:
            #     remote_participant_data = json.load(file)
            #     call_started_ts = remote_participant_data.get("joined_at")
            #     s3_client.upload_file(f'room_events_{ctx.room.name}.json', s3_bucket, f"meragi_inbound/{ctx.room.name}/room_events_{ctx.room.name}.json")
            #     os.remove(f'room_events_{ctx.room.name}.json')
            
            if os.path.exists(jsonl_filename):
                s3_client.upload_file(jsonl_filename, s3_bucket, s3_key)
                s3_client.upload_file(transcript_filename, s3_bucket, f"meragi_inbound/{ctx.room.name}/{transcript_filename}")
                s3_client.upload_file(summary_filename, s3_bucket, f"meragi_inbound/{ctx.room.name}/{summary_filename}")
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
                "recording_url": f"https://{os.getenv('S3_RECORDING_BUCKET')}.s3.{os.getenv('S3_RECORDING_REGION')}.amazonaws.com/meragi_inbound/{ctx.room.name}/call_recording_{ctx.room.name}.mp4",
                "transcript": session.history.to_dict(),
                "summary": summary.__dict__
            }

            # url = f"https://qualif.revspot.ai/livekit/webhook_listener/{bridge_id}"
            url = f"http://localhost:8001/livekit/webhook_listener/{bridge_id}"
            logger.info(f"Sending webhook to {url}")
            
            await send_webhook_to_qualif(data, url)
                
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")


    ctx.add_shutdown_callback(write_room_events)


    lkapi = api.LiveKitAPI()
    res = await lkapi.egress.start_room_composite_egress(req)

    agent = MeragiInboundAgent(customer_name=customer_name, dial_info=dial_info)

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
                sip_trunk_id=os.getenv("SIP_OUTBOUND_TRUNK_ID"),
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
        logger.error(f"Failed to create SIP participant: {e}")

        ctx.shutdown()
        await lkapi.aclose()
        return


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name="meragi-inbound-agent"))
    # cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
