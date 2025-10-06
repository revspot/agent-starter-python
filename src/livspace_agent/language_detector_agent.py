from __future__ import annotations

import logging
from typing import Any
import asyncio
from dotenv import load_dotenv

from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    FunctionToolsExecutedEvent,
    CloseEvent,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    metrics
)

from livekit.agents.llm import function_tool
from livekit.plugins import google, elevenlabs, silero, noise_cancellation, sarvam
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livspace_agent.utils.api_utils import get_api_data_async
from livspace_agent.englishAgent import LivspaceInboundEnglishAgent
from livspace_agent.hindiAgent import LivspaceInboundHindiAgent

logger = logging.getLogger("livspace-language-detector-agent")
load_dotenv(".env.local")

class LivspaceLanguageSwitchAgent(Agent):
    def __init__(self,
                chat_ctx=None,
                user_project_details=None):
        super().__init__(
            instructions="""You are a helpful voice AI assistant.
            Your job is to detect the language of the user's conversation and switch the conversation language to the user's preferred language.
            Donot try to extend the conversation for a long duration. Try to keep the conversation short and to the point.
            You are curious, friendly, and have a sense of humor.""",
            stt=elevenlabs.STT(
                language_code="en"
            ),
            llm=google.LLM(model="gemini-2.5-flash-lite"),
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
        logger.info(f"User project details: {self.user_project_details}")
    async def on_enter(self) -> None:
        await self.session.say("""
        Hi, thank you for calling to Livspace. Would you like to speak in Hindi or English?"""
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
        logger.info(f"Language detection function called with language: {language_code}")

        language_mapping = {
            "hi": {"deepgram": "hi", "elevenlabs": "hi"},
            "en": {"deepgram": "en", "elevenlabs": "en"}
        }

        if language_code not in language_mapping:
            logger.warning(f"Unsupported language code: {language_code}")
            return f"Sorry, I don't support the language code '{language_code}'. I can only speak Hindi (hi) and English (en)."

        if language_code == "hi":
            return "Your language preference is noted", LivspaceInboundHindiAgent(chat_ctx=self.chat_ctx, user_project_details=self.user_project_details)
        else:
            return "Your language preference is noted", LivspaceInboundEnglishAgent(chat_ctx=self.chat_ctx, user_project_details=self.user_project_details)
        
        # await self.session.say(
        #     instructions="I have noted your preference. I will now respond in this language.""
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

        logger.info(f"voice mail detection function called")

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

        logger.info("end_call function called")
        await context.session.say(text="Thank you for calling. Goodbye!", allow_interruptions=True)
        current_speech = context.session.current_speech
        if current_speech is not None:
            await current_speech.wait_for_playout()

        self._closing_task = asyncio.create_task(self.session.aclose())
        

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    """Entrypoint for the agent"""
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    await ctx.connect()

    # Set up a voice AI pipeline using OpenAI, Cartesia, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        false_interruption_timeout=0.5,  # Wait 0.5 second before resuming
        resume_false_interruption=True,   # Enable auto-resume
        # preemptive_generation=True,
    )

    
    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)
     
    @session.on("function_tools_executed")
    def _on_function_tools_executed(ev: FunctionToolsExecutedEvent):
        logger.info(f"Function tools executed")

    @session.on("close")
    def _on_close(ev: CloseEvent):
        logger.info(f"Session closed")
        ctx.delete_room()

    phone_number = "8511117231"
    user_project_details = await get_api_data_async(
        url="https://api.livspace.com/sales/crm/api/v1/projects/search",
        params={
            "filters": f"(customer.phone\n=lk={phone_number})",
            "order_by": "id:desc",
            "count": 100,
            "select": "id,stage.display_name,created_at,customer.email,status,city,pincode,property_name"
        },
        timeout=10
    )
    logger.info(f"Successfully fetched user_details")
    
    agent = LivspaceLanguageSwitchAgent(user_project_details=user_project_details)

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # LiveKit Cloud enhanced noise cancellation
            # - If self-hosting, omit this parameter
            # - For telephony applications, use `BVCTelephony` for best results
            # Temporarily disabled due to FFI handle error
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))