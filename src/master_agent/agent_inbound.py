from __future__ import annotations

import logging
import os
from typing import Any
import asyncio
import aiohttp
import hashlib
import io
import json

from dotenv import load_dotenv
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentStateChangedEvent,
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
    cli,
    metrics,
)
from livekit import api
from livekit.agents.llm import function_tool
from livekit.plugins import deepgram, noise_cancellation, openai, silero, google, elevenlabs, groq
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from master_agent.regalia import INSTRUCTIONS

logger = logging.getLogger("agent")

load_dotenv(".env.local")

class Assistant(Agent):
    def __init__(self, chat_ctx = None) -> None:
        super().__init__(
            instructions=INSTRUCTIONS.replace("{{salutation}}", "Mr." ).replace("{{customer_name}}", "Subham").replace("{{lead_honorific}}", "Sir"),
            chat_ctx=chat_ctx,
        )

    async def on_enter(self) -> None:
        greeting_time = "morning"
        salutation = "Mr."
        customer_name = "Subham"
        await self.session.say(f"Good {greeting_time}, am I speaking with {salutation} {customer_name}?")

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

    @function_tool
    async def end_call(self, reason: str, context: RunContext):
        """Gracefully conclude conversations when appropriate
            Args:
                reason: The reason for ending the call
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

        logger.info(f"end_call function called with reason: {reason}")
        await context.session.say(f"Thank you for your time Mr Das. Goodbye!", allow_interruptions=True)
        current_speech = context.session.current_speech
        if current_speech is not None:
            await current_speech.wait_for_playout()

        self._closing_task = asyncio.create_task(self.session.aclose())

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    dial_info = ctx.job.metadata
    logger.info(f"dial_info: {dial_info}")

    for participant in ctx.room.remote_participants:
        if participant.kind == "SIP":
            # Extract SIP attributes
            call_id = participant.attributes.get("sip.callID", "Unknown")
            phone_number = participant.attributes.get("sip.phoneNumber", "Unknown")
            call_status = participant.attributes.get("sip.callStatus", "Unknown")

            # Log or use the extracted attributes
            logger.info(f"SIP Call ID: {call_id}")
            logger.info(f"Phone Number: {phone_number}")
            logger.info(f"Call Status: {call_status}")

    # Initialize BackgroundAudioPlayer inside the async context
    background_audio_player = BackgroundAudioPlayer(
        # thinking_sound=[
        #     AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.8),
        #     AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.7),
        # ],
        ambient_sound=[
            AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.5),
        ]
    )

    # Set up a voice AI pipeline using OpenAI, Cartesia, Deepgram, and the LiveKit turn detector
    session = AgentSession(
    #     # A Large Language Model (LLM) is your agent's brain, processing user input and generating a response
    #     # See all providers at https://docs.livekit.io/agents/integrations/llm/
    #     # llm=openai.LLM(model="gpt-4o-mini"),
        llm=google.LLM(
            model="gemini-2.5-flash",
            temperature=0.2,
            max_output_tokens=4096
            ),
        # llm=groq.LLM(
        #     model="openai/gpt-oss-20b",
        #     temperature=0.0,
        #     ),
    #     # Speech-to-text (STT) is your agent's ears, turning the user's speech into text that the LLM can understand
    #     # See all providers at https://docs.livekit.io/agents/integrations/stt/
        stt=deepgram.STT(
            model="nova-3",
            language="en-IN",
            detect_language=False,
            punctuate=True,
            smart_format=True,
            sample_rate=16000,
            endpointing_ms=25,
            # filler_words=False,
            # keyterms=[],
        ),
    #     # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
    #     # See all providers at https://docs.livekit.io/agents/integrations/tts/
        tts=elevenlabs.TTS(
                model="eleven_flash_v2_5", 
                voice_id="pzxut4zZz4GImZNlqQ3H",
                voice_settings=elevenlabs.VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.7,
                    speed=1.12,
                ),
                streaming_latency=4
                ),
    #     # VAD and turn detection are used to determine when the user is speaking and when the agent should respond
    #     # See more at https://docs.livekit.io/agents/build/turns
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        false_interruption_timeout=1.0,  # Wait 0.5 second before resuming
        resume_false_interruption=True,   # Enable auto-resume
    #     # allow the LLM to generate a response while waiting for the end of turn
    #     # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
        # preemptive_generation=True,
        min_interruption_words=2
    )

    # session = AgentSession(
    #     llm=openai.realtime.RealtimeModel(
    #         model="gpt-4o-realtime-preview",
    #         # modalities=["audio, 'text"],
    #         voice="marin",
    #         temperature=0.8,
    #         speed=1.10
    #     ),
    # )

    # sometimes background noise could interrupt the agent session, these are considered false positive interruptions
    # when it's detected, you may resume the agent's speech
    # @session.on("agent_false_interruption")
    # def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
    #     logger.info("false positive interruption, resuming")
    #     session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)

    # Metrics collection, to measure pipeline performance
    # For more information, see https://docs.livekit.io/agents/build/metrics/
    usage_collector = metrics.UsageCollector()

    async def user_presence_task():
        for _ in range(3):
            await session.generate_reply(
                instructions="The user has been inactive. Politely check if they're still present."
            )
            await asyncio.sleep(5)
        session.shutdown()

    @session.on("user_state_changed")
    def _user_state_changed(ev: UserStateChangedEvent):
        if ev.new_state == "away":
            asyncio.create_task(user_presence_task())

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    @session.on("close")
    def _on_close(ev: CloseEvent):
        logger.info(f"Session closed")
        ctx.delete_room()


    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/integrations/avatar/
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/integrations/avatar/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    #Join the room and connect to the user
    await ctx.connect()

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

    await background_audio_player.start(
        room=ctx.room,
        agent_session=session,
    )
    background_audio_player.play(
        AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=3.0),
        loop=True
    )

    # @session.on("agent_state_changed")
    # def _on_agent_state_changed(ev: AgentStateChangedEvent):
    #     if ev.new_state == "thinking":
    #         background_audio_player.play(
    #             AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.4),
    #         )
    #     # if ev.new_state == "idle":
    #     #     background_audio_player.play(
    #     #         AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.5),
    #     #     )
    #     if ev.new_state == "speaking":
    #         background_audio_player.stop()

    # await background_audio_player.aclose()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name="livekit_master_inbound_agent"))
