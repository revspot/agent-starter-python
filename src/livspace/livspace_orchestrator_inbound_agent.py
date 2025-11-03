from __future__ import annotations

import logging
import os
import hashlib
import asyncio
import aiohttp
import json
import uuid
from dotenv import load_dotenv
from typing import Any

from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    FunctionToolsExecutedEvent,
    CloseEvent,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    BackgroundAudioPlayer,
    AudioConfig,
    BuiltinAudioClip,  
    cli,
    metrics
)
from livekit import api, rtc
from livekit.agents.llm import function_tool
from livekit.plugins import elevenlabs, silero, noise_cancellation, groq
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from utils.api_utils import get_api_data_async
from livspace.englishAgent import LivspaceInboundEnglishAgent
from livspace.hindiAgent import LivspaceInboundHindiAgent

logger = logging.getLogger("livspace-language-detector-agent")
load_dotenv(".env.local")

class LivspaceLanguageSwitchAgent(Agent):
    def __init__(self,
                chat_ctx=None,
                user_project_details=None,
                dial_info: dict[str, Any]=None
                ):
        super().__init__(
            instructions="""You are a helpful voice AI assistant.
            Your job is to detect the language of the user's conversation and switch the conversation language to the user's preferred language.
            Donot try to extend the conversation for a long duration. Try to keep the conversation short and to the point.
            You are curious, friendly, and have a sense of humor.
            
            After taking the language preference, call the language_detection function with the language code.
            
            GUARDRAILS:
            - Stick to the script. If someone asks something that is not in the script, reply with "I'm sorry, I can't help with that."
            - After taking the language preference, let the agent handle the conversation.
            - Do not speak out any tool calls or any of their errors.

            """,
            stt=elevenlabs.STT(
                language_code="en"
            ),
            llm=groq.LLM(model="openai/gpt-oss-20b", temperature=0.4),
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
            turn_detection=MultilingualModel(),
            chat_ctx=chat_ctx,
        )
        self.user_project_details = user_project_details
        self.dial_info = dial_info
        logger.info(f"[room: {self.dial_info['room_name']}] -- User project details: {self.user_project_details}")
    async def on_enter(self) -> None:
        await self.session.say("""
        Hi, thank you for calling Livspace. Would you like to speak in Hindi or English?"""
        )
        
    @function_tool
    async def language_detection(self, context: RunContext, language_code: str):
        """
        Language Detection Tool:
        Detect the language of the user's conversation and switch the conversation language to the user's preferred language.
        Call this function when:
        - Direct requests: "Can we speak in Hindi?", "Switch to Hindi", "Let's continue in Hindi"
        - Questions about capability: "Do you speak Hindi?", "क्या आप हिंदी में बात करते हैं?"
        - Stated preferences: "I would prefer Hindi", "Hindi would be better for me"
        - Speaks in Hindi: "मुझे नया घर चाहिए"

        Do not call this function when user mentions the language but doesn't request to speak it.

        Following languages are allowed to be selected: ["hi": "Hindi", "en": "English"]
        If target language is not in the list, let user know that you can't speak the target language.

        EXAMPLE FLOWS:

        Example 1 (explicit):
        Assistant: "Hi, How can I help you today?"
        User: "I not speak English, speak Hindi."
        Assistant: [language_detection function called with language="hi"] "नमस्ते, आज मैं आपको कैसे मदद कर सकता हूं?"

        Example 2 (language detection):
        Assistant: "Hi, How can I help you today?"
        User: "मुझे नया घर चाहिए"
        Assistant: [language_detection function called with language="hi"] "नमस्ते, आज मैं आपको कैसे मदवाई कर सकता हूं?"

        Example 3 (DO NOT call):
        User: "Do people in India speak Hindi?"
        Assistant: "Yes, many people in India speak Hindi."
        """
        logger.info(f"[room: {self.dial_info['room_name']}] -- Language detection function called with language: {language_code}")

        language_mapping = {
            "hi": {"deepgram": "hi", "elevenlabs": "hi"},
            "en": {"deepgram": "en", "elevenlabs": "en"}
        }

        if language_code not in language_mapping:
            logger.warning(f"[room: {self.dial_info['room_name']}] -- Unsupported language code: {language_code}")
            return f"Sorry, I don't support the language '{language_code}'. I can only speak Hindi (hi) and English (en)."

        if language_code == "hi":
            logger.info(f"[room: {self.dial_info['room_name']}] -- Switching to Hindi agent")
            return LivspaceInboundHindiAgent(chat_ctx=self.chat_ctx, user_project_details=self.user_project_details)
        else:
            logger.info(f"[room: {self.dial_info['room_name']}] -- Switching to English agent")
            return LivspaceInboundEnglishAgent(chat_ctx=self.chat_ctx, user_project_details=self.user_project_details)
        
        # await self.session.say(
        #     instructions="I have noted your preference. I will now respond in this language."
        # )

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

        logger.info(f"[room: {self.dial_info['room_name']}] -- voice mail detection function called")

        self._closing_task = asyncio.create_task(self.session.aclose())

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

        logger.info(f"[room: {self.dial_info['room_name']}] -- end_call function called")
        await context.session.say(text="Thank you for calling. Goodbye!", allow_interruptions=True)
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
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    logger.info(f"[room: {ctx.room.name}] -- connecting to room")
    await ctx.connect()
    room_id = await ctx.room.sid
    logger.info(f"[room: {ctx.room.name}] -- connected to room, room_id: {room_id}")
    phone_number = ctx.room.name.split("_")[1]
    clean_phone_number = phone_number.replace("+91", "")
    logger.info(f"[room: {ctx.room.name}] -- phone number: {phone_number}")
    logger.info(f"[room: {ctx.room.name}] -- clean phone number: {clean_phone_number}")
    dial_info = {
        "phone_number": phone_number,
        "room_name": ctx.room.name,
    }

    s3_file_name_hash = hashlib.sha256(ctx.room.name.encode('utf-8')).hexdigest()
    recording_file_name=f"call_recording_{s3_file_name_hash}.mp4"

    # Prepare egress request, but start only after audio is present
    req = api.RoomCompositeEgressRequest(
        room_name=ctx.room.name,
        layout="grid",
        audio_only=True,
        file_outputs=[
            api.EncodedFileOutput(
                file_type=api.EncodedFileType.MP4,
                filepath=recording_file_name,
                s3=api.S3Upload(
                    access_key=os.getenv("AWS_ACCESS_KEY_ID"),
                    secret=os.getenv("AWS_SECRET_ACCESS_KEY"),
                    bucket=os.getenv("S3_RECORDING_BUCKET"),
                    region=os.getenv("S3_RECORDING_REGION"),   # pick your S3 bucket region
                ),
            ),
        ],
    )

    background_audio_player = BackgroundAudioPlayer(
        ambient_sound=[
            AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.5),
        ]
    )


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

    @session.on("function_tools_executed")
    def _on_function_tools_executed(ev: FunctionToolsExecutedEvent):
        # filename = write_event_jsonl(ev.model_dump())
        data = ev.model_dump()
        data["event"] = "function_tools_executed"
        data["room"] = {"sid": room_id}
        url = f"https://qualif.revspot.ai/livekit/events"
        asyncio.create_task(send_webhook_to_qualif(data, url, ctx.room.name))
        logger.info(f"Function tools executed")
    
    @session.on("close")
    def _on_close(ev: CloseEvent):
    #     filename = write_event_jsonl(ev.model_dump())
        # logger.info(f"Close: {filename}")
        logger.info(f"Session closed")
        data = ev.model_dump()
        data["event"] = "session_closed"
        data["room"] = {"sid": room_id}
        url = f"https://qualif.revspot.ai/livekit/events"
        asyncio.create_task(send_webhook_to_qualif(data, url, ctx.room.name))
        ctx.delete_room()
        # await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
    

    async def write_room_events():
            
        try:
            # Get summary safely for webhook
            summary = usage_collector.get_summary() if usage_collector else None
            
            data = {
                "conversation_id": ctx.room.name,
                "status": "completed",
                "room_id": room_id,
                "recording_url": f"https://recordings.qualif.revspot.ai/{recording_file_name}",
                "transcript": session.history.to_dict(),
                "summary": summary.__dict__ if summary else {}
            }
            APP_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "qualif.revvspot.ai")
            bridge_id = uuid.uuid5(APP_NAMESPACE, f"{room_id}:{ctx.room.name}")

            url = f"https://qualif.revspot.ai/livekit/webhook_listener/{bridge_id}"
            logger.info(f"[room: {ctx.room.name}] -- Sending webhook to {url}")
            
            await send_webhook_to_qualif(data, url, ctx.room.name)
                
        except Exception as e:
            logger.error(f"[room: {ctx.room.name}] -- Failed to send webhook: {e}")


    ctx.add_shutdown_callback(write_room_events)

    user_project_details = await get_api_data_async(
        url="https://ls-proxy.revspot.ai/canvas/projects/search",
        params={
            "filters": f"(customer.phone=lk={clean_phone_number})",
            "order_by": "id:desc",
            "count": 100,
            "select": "id,stage.display_name,created_at,customer.email,status,city,pincode,property_name"
        },
        timeout=10
    )

    lkapi = api.LiveKitAPI()
    egress_id: str | None = None

    agent = LivspaceLanguageSwitchAgent(dial_info=dial_info, user_project_details=user_project_details)
    # agent = LivspaceInboundAgent(dial_info=dial_info)

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVCTelephony(),
        ),
    )

    try:
        res = await lkapi.egress.start_room_composite_egress(req)
        egress_id = getattr(res, "egress_id", None)
        logger.info(f"[room: {ctx.room.name}] -- Started egress: {egress_id}")
    except Exception as e:
        logger.error(f"[room: {ctx.room.name}] -- Failed to start egress: {e}")

    async def _egress_watchdog():
        try:
            # Fixed timeout watchdog: wait 5 minutes then attempt a best-effort stop
            await asyncio.sleep(600)
            if egress_id:
                try:
                    await lkapi.egress.stop_egress(api.StopEgressRequest(egress_id=egress_id))
                    logger.info(f"[room: {ctx.room.name}] -- Watchdog stop issued for egress after timeout: {egress_id}")
                except Exception as stop_err:
                    logger.warning(f"[room: {ctx.room.name}] -- Watchdog stop failed: {stop_err}")
        except Exception as err:
            logger.warning(f"[room: {ctx.room.name}] -- Egress watchdog error: {err}")

    asyncio.create_task(_egress_watchdog())

    async def _stop_egress_on_close():
        if egress_id:
            try:
                await lkapi.egress.stop_egress(api.StopEgressRequest(egress_id=egress_id))
                logger.info(f"[room: {ctx.room.name}] -- Stopped egress on close: {egress_id}")
            except Exception as e:
                logger.warning(f"[room: {ctx.room.name}] -- Failed to stop egress on close: {e}")

    ctx.add_shutdown_callback(_stop_egress_on_close)

    await background_audio_player.start(
        room=ctx.room,
        agent_session=session,
    )
    background_audio_player.play(
        AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=2.0),
        loop=True
    )

    await lkapi.aclose()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name="livspace_orchestrator_inbound_agent", job_memory_warn_mb=1024))
    
