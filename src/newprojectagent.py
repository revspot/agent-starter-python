from livekit.agents import Agent, function_tool, RunContext, get_job_context
from livekit.plugins import deepgram, openai, elevenlabs, google
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from constants import NEW_PROJECT_INSTRUCTIONS
from livekit import api


class NewProjectAgent(Agent):
    """Specialized agent for new project"""

    def __init__(self, chat_ctx=None):
        __name__ = "new-project-agent"
        super().__init__(
            instructions=NEW_PROJECT_INSTRUCTIONS,
            stt=deepgram.STT(),
            llm=google.LLM(model="gemini-2.5-flash-lite"),
            tts=elevenlabs.TTS(voice_id="GHKbgpqchXOxta6X2lSd"),
            turn_detection=MultilingualModel(),
            chat_ctx=chat_ctx,
        )

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions="Introduce yourself as Varsha from the New Project team and ask how you can help them get started with their new home interior project.",
            allow_interruptions=True,
        )

    @function_tool
    async def return_to_main_agent(self, context: RunContext):
        """Return control back to the main assistant.

        Use this when the user wants to go back to general assistance or
        needs help with something other than new project.
        """
        from agent import LivspaceAgent

        await self.session.generate_reply(
            instructions="I'll transfer you back to our main assistant who can help with other topics."
        )
        return "Returning to main assistant", LivspaceAgent(chat_ctx=self.chat_ctx)

    @function_tool
    async def schedule_site_visit(self, context: RunContext, day: str, time: str):
        """When you schedule a site visit for the user, use this tool."""
        return "I have scheduled a site visit for you on {day} at {time}."
        

    @function_tool
    async def schedule_ec_visit(self, context: RunContext):
        """When you schedule an Experience Centre visit for the user, use this tool."""
        return "I have scheduled an Experience Centre visit for you on {day} at {time}."

    @function_tool
    async def end_call(self, context: RunContext):
        """When you decide to end the call after the end of conversation, use this tool."""

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
            pass
