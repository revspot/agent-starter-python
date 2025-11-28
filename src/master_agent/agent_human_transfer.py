from __future__ import annotations

import logging
import os
from typing import Any
import asyncio
import aiohttp
import hashlib
import io
import json
import uuid

from dotenv import load_dotenv
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentStateChangedEvent,
    FunctionToolsExecutedEvent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    CloseEvent,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    AutoSubscribe,
    UserStateChangedEvent,
    BackgroundAudioPlayer,
    AudioConfig,
    BuiltinAudioClip,
    get_job_context,
    cli,
    metrics,
)
from livekit import api, rtc
from livekit.agents.llm import function_tool
from livekit.plugins import deepgram, noise_cancellation, openai, silero, google, elevenlabs, groq, cartesia
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from master_agent.regalia import INSTRUCTIONS, ENTER_INSTRUCTIONS, EXIT_INSTRUCTIONS

logger = logging.getLogger("agent")
load_dotenv(".env.local")

class Agent(Agent):
    def __init__(self,
                 chat_ctx=None,
                 enter_instructions=None,
                 instructions=None,
                 exit_instructions=None,
                 dial_info: dict[str, Any]=None):
        self.__name__ = "livekit_human_transfer_agent"
        super().__init__(
            instructions=instructions.replace("{{salutation}}", "Mr.").replace("{{customer_name}}", "Subham"),
            stt=deepgram.STT(
                model="nova-3",
                language="en-IN",
                detect_language=False,
                punctuate=True,
                smart_format=True,
                sample_rate=16000,
                endpointing_ms=25,
                filler_words=True,
                profanity_filter=False,
                numerals=False,
                enable_diarization=False,
            ),
            llm=groq.LLM(
                model="openai/gpt-oss-120b",
                temperature=0.4
            ),
            tts=cartesia.TTS(
                model="sonic-3",
                voice="22bb5a1d-627e-484a-9e0c-eeda819abb95"
            ),
            chat_ctx=chat_ctx,
        )
        self.enter_instructions = enter_instructions.replace("{{salutation}}", "Mr.").replace("{{customer_name}}", "Subham")
        self.exit_instructions = exit_instructions.replace("{{salutation}}", "Mr.").replace("{{customer_name}}", "Subham")
        self.dial_info = dial_info
        self.participant: rtc.RemoteParticipant | None = None

    async def on_enter(self) -> None:
        if self.enter_instructions:
            await self.session.say(self.enter_instructions)

    @function_tool
    async def transfer_call(self, context: RunContext, reason: str | None = None):
        """
        Transfer the conversation to a human agent when appropriate.
        Call this function when:
        - Direct requests: "I want to speak to a human", "Connect me with a representative", "Transfer me to an agent"
        - Technical limitations: The user needs something beyond your capabilities
        - Complex issues: Problems requiring human judgment or access to systems beyond your reach

        Before calling this function, try to assist the user first if the request is within your capabilities.

        Do not call this function when:
        - You can answer basic information requests yourself
        - You can complete simple tasks within your capabilities
        - The user hasn't explicitly requested human assistance for complex issues

        EXAMPLE FLOWS:

        Example 1 (explicit request):
        User: "I want to talk to a real person instead of an AI. Please connect me to a human agent."
        Assistant: "I understand you'd prefer to speak with a human agent. I'm arranging that connection for you now, and a human representative will assist you shortly."
        [transfer_to_number function called]

        Example 2 (technical limitation):
        User: "I need to change my billing address and payment method for my order #12345."
        Assistant: "I understand you need to update your billing information. Since this requires accessing your account details, I'll connect you with a human representative who can help you with that change safely."
        [transfer_to_number function called]

        Example 3 (DO NOT call):
        User: "What's your refund policy?"
        Assistant: "Our standard refund policy allows returns within 30 days of purchase with a receipt. Would you like more specific information about a particular product or situation?"
        """

        transfer_to = self.dial_info["transfer_to"]
        if not transfer_to:
            await context.session.say("I'm sorry, I cannot transfer the call right now. I can help schedule a callback for you.")
            # self._closing_task = asyncio.create_task(self.session.aclose())
            raise Exception("human agent number not provided")

        logger.info(f"transferring call to {transfer_to}")

        # let the message play fully before transferring
        await context.session.say("I'll be transferring you to my team. Please hold on while I connect you.")
        job_ctx = get_job_context()
        try:
            await job_ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                    room_name=job_ctx.room.name,
                    sip_trunk_id=self.dial_info["sip_trunk_id"],
                    sip_call_to=transfer_to,
                    participant_identity=transfer_to,
                    # function blocks until user answers the call, or if the call fails
                    wait_until_answered=True,
                )
            )

            participant = await job_ctx.wait_for_participant(identity=transfer_to)
            logger.info(f"participant joined: {participant.identity}")

            await job_ctx.api.room.remove_participant(api.RoomParticipantIdentity(
                room=job_ctx.room.name,
                identity=job_ctx.room.local_participant.identity
            ))
            logger.info(f"Agent disconnected")
            logger.info(f"transferred call to {transfer_to}")
        except Exception as e:
            logger.error(f"error transferring call to {transfer_to}: {e}")
            await context.session.say("I'm sorry, I cannot transfer the call right now. I will schedule a callback for you.")
            self._closing_task = asyncio.create_task(self.session.aclose())

    @function_tool
    async def voice_mail_detection(self, context: RunContext, reason: str | None = None):
        """Detect when a call has been answered by a voicemail system rather than a human.
            Call this function when you detect that the call recipient is not available and the call has been answered by an automated voicemail system.

            Common indicators of voicemail:
            - Automated greeting messages: "You have reached the voicemail of..."
            - Recording instructions: "Please leave a message after the beep/tone"
            - Voicemail system prompts: "Please leave your name and number"
            - Generic unavailable messages: "The number you have dialed is not available"

            After calling this function:
            - If a voicemail message is configured, it will be played automatically
            - The call will end immediately after the message (or immediately if no message)
            - No further conversation will take place

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
            """

        logger.info(f"voice mail detection function called")

        self._closing_task = asyncio.create_task(self.session.aclose())

    @function_tool
    async def end_call(self, context: RunContext, reason: str | None = None):
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
        await context.session.say(self.exit_instructions)
        current_speech = context.session.current_speech
        if current_speech is not None:
            await current_speech.wait_for_playout()

        self._closing_task = asyncio.create_task(self.session.aclose())

    def set_participant(self, participant: rtc.RemoteParticipant):
        self.participant = participant

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def send_webhook_to_qualif(data: dict, url: str, room_name: str):
    """Send webhook to Qualif"""
    logger.info(f"[room: {room_name}] -- Sending webhook to {url}")
    async with aiohttp.ClientSession() as http_session:
        async with http_session.post(url, json=data) as response:
            if response.status == 200 or response.status == 201:
                logger.info(f"[room: {room_name}] -- Webhook sent successfully to {url}, Response: {response.status}")
            else:
                logger.error(f"[room: {room_name}] -- Failed to send webhook: {response.status}")
                error_message = await response.text()
                logger.error(f"[room: {room_name}] -- Error message: {error_message}")
                raise Exception(f"[room: {room_name}] -- Webhook failed with status {response.status}: {error_message}")


async def entrypoint(ctx: JobContext):
    """Entrypoint for the agent"""
    # ctx.log_context_fields = {
    #     "room": ctx.room.name,
    # }
    # logger.info(f"[room: {ctx.room.name}] -- connecting to room")
    await ctx.connect()
    # room_id = await ctx.room.sid
    # logger.info(f"[room: {ctx.room.name}] -- connected to room, room_id: {room_id}")
    # phone_number = ctx.room.name.split("_")[1]
    # clean_phone_number = phone_number.replace("+91", "")
    # logger.info(f"[room: {ctx.room.name}] -- phone number: {phone_number}")
    # logger.info(f"[room: {ctx.room.name}] -- clean phone number: {clean_phone_number}")
    dial_info = {
    #     "phone_number": phone_number,
        "room_name": ctx.room.name,
        # "transfer_to": '+917978884674',
        "sip_trunk_id": 'ST_bmw4anKattdp',
    }
    # job_metadata = json.loads(ctx.job.metadata)
    # agent_id = job_metadata.get('agent_id')
    # logger.info(f"[room: {ctx.room.name}] -- agent id: {agent_id}")

    # s3_file_name_hash = hashlib.sha256(ctx.room.name.encode('utf-8')).hexdigest()
    # recording_file_name=f"call_recording_{s3_file_name_hash}.mp4"

    # # Prepare egress request, but start only after audio is present
    # req = api.RoomCompositeEgressRequest(
    #     room_name=ctx.room.name,
    #     layout="grid",
    #     audio_only=True,
    #     file_outputs=[
    #         api.EncodedFileOutput(
    #             file_type=api.EncodedFileType.MP4,
    #             filepath=recording_file_name,
    #             s3=api.S3Upload(
    #                 access_key=os.getenv("AWS_ACCESS_KEY_ID"),
    #                 secret=os.getenv("AWS_SECRET_ACCESS_KEY"),
    #                 bucket=os.getenv("S3_RECORDING_BUCKET"),
    #                 region=os.getenv("S3_RECORDING_REGION"),   # pick your S3 bucket region
    #             ),
    #         ),
    #     ],
    # )

    # background_audio_player = BackgroundAudioPlayer(
    #     ambient_sound=[
    #         AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.5),
    #     ]
    # )

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        false_interruption_timeout=1,  # Wait 1 second before resuming
        resume_false_interruption=True,   # Enable auto-resume
        min_interruption_duration=0.5,
        min_interruption_words=2,
    )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def user_presence_task():
        for _ in range(3):
            await session.generate_reply(
                instructions="The user has been inactive. Politely check if they're still present."
            )
            await asyncio.sleep(10)
        session.shutdown()

    @session.on("user_state_changed")
    def _user_state_changed(ev: UserStateChangedEvent):
        if ev.new_state == "away":
            asyncio.create_task(user_presence_task())

    # @session.on("function_tools_executed")
    # def _on_function_tools_executed(ev: FunctionToolsExecutedEvent):
    #     # filename = write_event_jsonl(ev.model_dump())
    #     data = ev.model_dump()
    #     data["event"] = "function_tools_executed"
    #     data["room"] = {"sid": room_id}
    #     url = f"https://qualif.revspot.ai/livekit/events"
    #     asyncio.create_task(send_webhook_to_qualif(data, url, ctx.room.name))
    #     logger.info(f"Function tools executed")
    
    # @session.on("close")
    # def _on_close(ev: CloseEvent):
    # #     filename = write_event_jsonl(ev.model_dump())
    #     # logger.info(f"Close: {filename}")
    #     logger.info(f"Session closed")
    #     data = ev.model_dump()
    #     data["event"] = "session_closed"
    #     data["room"] = {"sid": room_id}
    #     url = f"https://qualif.revspot.ai/livekit/events"
    #     asyncio.create_task(send_webhook_to_qualif(data, url, ctx.room.name))
    #     ctx.delete_room()
    #     # await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
    

    # async def write_room_events():
            
    #     try:
    #         # Get summary safely for webhook
    #         summary = usage_collector.get_summary() if usage_collector else None
            
    #         data = {
    #             "agent_identifier": agent_id,
    #             "conversation_id": ctx.room.name,
    #             "status": "completed",
    #             "room_id": room_id,
    #             "recording_url": f"https://recordings.qualif.revspot.ai/{recording_file_name}",
    #             "transcript": session.history.to_dict(),
    #             "summary": summary.__dict__ if summary else {}
    #         }
    #         APP_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "qualif.revvspot.ai")
    #         bridge_id = uuid.uuid5(APP_NAMESPACE, f"{room_id}:{ctx.room.name}")

    #         url = f"https://qualif.revspot.ai/livekit/webhook_listener/{bridge_id}"
    #         logger.info(f"[room: {ctx.room.name}] -- Sending webhook to {url}")
            
    #         await send_webhook_to_qualif(data, url, ctx.room.name)
                
    #     except Exception as e:
    #         logger.error(f"[room: {ctx.room.name}] -- Failed to send webhook: {e}")


    # ctx.add_shutdown_callback(write_room_events)

    # lkapi = api.LiveKitAPI()
    # egress_id: str | None = None

    agent = Agent(dial_info=dial_info, enter_instructions=ENTER_INSTRUCTIONS, exit_instructions=EXIT_INSTRUCTIONS, instructions=INSTRUCTIONS)

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVCTelephony(),
        ),
    )

    # try:
    #     res = await lkapi.egress.start_room_composite_egress(req)
    #     egress_id = getattr(res, "egress_id", None)
    #     logger.info(f"[room: {ctx.room.name}] -- Started egress: {egress_id}")
    # except Exception as e:
    #     logger.error(f"[room: {ctx.room.name}] -- Failed to start egress: {e}")

    # async def _egress_watchdog():
    #     try:
    #         # Fixed timeout watchdog: wait 5 minutes then attempt a best-effort stop
    #         await asyncio.sleep(600)
    #         if egress_id:
    #             try:
    #                 await lkapi.egress.stop_egress(api.StopEgressRequest(egress_id=egress_id))
    #                 logger.info(f"[room: {ctx.room.name}] -- Watchdog stop issued for egress after timeout: {egress_id}")
    #             except Exception as stop_err:
    #                 logger.warning(f"[room: {ctx.room.name}] -- Watchdog stop failed: {stop_err}")
    #     except Exception as err:
    #         logger.warning(f"[room: {ctx.room.name}] -- Egress watchdog error: {err}")

    # asyncio.create_task(_egress_watchdog())

    # async def _stop_egress_on_close():
    #     if egress_id:
    #         try:
    #             await lkapi.egress.stop_egress(api.StopEgressRequest(egress_id=egress_id))
    #             logger.info(f"[room: {ctx.room.name}] -- Stopped egress on close: {egress_id}")
    #         except Exception as e:
    #             logger.warning(f"[room: {ctx.room.name}] -- Failed to stop egress on close: {e}")

    # ctx.add_shutdown_callback(_stop_egress_on_close)


    # await background_audio_player.start(
    #     room=ctx.room,
    #     agent_session=session,
    # )
    # background_audio_player.play(
    #     AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=2.0),
    #     loop=True
    # )

    # await lkapi.aclose()

if __name__ == "__main__":
    # cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name="livekit_master_inbound_agent", job_memory_warn_mb=1024, job_memory_limit_mb=1024))
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, job_memory_warn_mb=1024, job_memory_limit_mb=1024))
