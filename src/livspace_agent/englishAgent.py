from __future__ import annotations

import logging
from typing import Any
import asyncio
from dotenv import load_dotenv

from livekit.agents import (
    NOT_GIVEN,
    Agent,
    RunContext
)

from livekit.agents.llm import function_tool
from livekit.plugins import google, elevenlabs, sarvam
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livspace_agent.pincodes import serviceable_pincodes
from livspace_agent.englishPrompt import INSTRUCTIONS

logger = logging.getLogger("livspace-inbound-english-agent")
load_dotenv(".env.local")

class LivspaceInboundEnglishAgent(Agent):
    def __init__(self,
                 chat_ctx=None,
                 user_project_details=None):
        super().__init__(
            instructions=INSTRUCTIONS,
            stt=elevenlabs.STT(
                language_code="en"
            ),
            llm=google.LLM(model="gemini-2.5-flash-lite"),
            tts=elevenlabs.TTS(
                model="eleven_flash_v2_5", 
                voice_id="90ipbRoKi4CpHXvKVtl0",
                language="en",
                voice_settings=elevenlabs.VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.8,
                    speed=1.12,
                ),
                streaming_latency=4
                ),
            turn_detection=MultilingualModel(),
            chat_ctx=chat_ctx,
        )
        self.user_project_details = user_project_details

    async def on_enter(self) -> None:
        # await self.sessions.generate_reply(instructions=INSTRUCTIONS)
        await self.session.say("I have noted your preference. I will now respond in English.", allow_interruptions=False)

    @function_tool
    async def get_project_details(self, context: RunContext):
        """ Retrieves details for an existing customer's project using either their Project ID or registered mobile number (phone number).

        Returns:
            A dictionary with the details of the project.
        """
        return self.user_project_details

    @function_tool
    async def check_serviceability(self, context: RunContext, pincode: str):
        """
        Checks if Livspace provides services for a given pin code.

        Args:
            pincode: The 6-digit pin code to check serviceability for (e.g. "560034").

        Returns:
            A dictionary with the following keys:
            - serviceable: True if Livspace provides services for the given pin code, False otherwise.
            - city: The city that Livspace provides services for the given pin code.
            - error: The error message if the pin code is invalid.
        """
        logger.info(f"Checking serviceability for {pincode}")
        if len(pincode) != 6:
            return {'serviceable': False, 'error': 'Invalid pin code. Please enter a valid 6-digit pin code.'}

        for city, pincodes in serviceable_pincodes.items():
            if int(pincode) in pincodes:
                return {'serviceable': True, 'city': city}
        return {'serviceable': False}
        
    @function_tool
    async def get_minimum_budget(self, context: RunContext, city: str, project_type: str):
        """
        Fetches the minimum budget requirement for a specific city and project type.

        Args:
            city: The city to get the minimum budget for (e.g. "Bangalore").
            project_type: The type of project to get the minimum budget for, must be either ("new_build" or "renovation").

        Returns:
            A dictionary with the following keys:
            - minimum_budget: The minimum budget requirement for the given city and project type.
            - error: The error message if the city or project type is invalid, None if successful.
        """

        return {'minimum_budget': 100000, 'error': None}

    @function_tool
    async def create_lead_ticket(self, context: RunContext, name: str, phone: str, email: str, city: str, pincode: str, project_type: str, scope_summary: str, budget: int):
        """
        Creates a new lead ticket in the CRM for a qualified potential customer.

        Args:
            name: The name of the customer (e.g. "John Doe").
            phone: The phone number of the customer (e.g. "9876543210").
            email: The email of the customer (e.g. "john.doe@example.com").
            city: The city of the customer (e.g. "Bangalore").
            pincode: The pin code of the customer (e.g. "560034").
            project_type: The type of project to create a lead ticket for, must be either ("new_build" or "renovation").
            scope_summary: The scope of the project (e.g. "Kitchen renovation").
            budget: The budget for the project (e.g. 100000).

        Returns:
            A dictionary with the following keys:
            - success: True if the lead ticket was created successfully, False otherwise.
            - lead_id: The ID of the lead ticket if created successfully, None otherwise.
            - error: The error message if the lead ticket was not created successfully, None if successful.
        """

        return {'success': True, 'lead_id': '123456', 'error': None}

    @function_tool
    async def schedule_appointment(self, context: RunContext, lead_id: str, appointment_type: str, datetime: str, notes: str):
        """
        Schedules an appointment (briefing call or site visit) for a new lead.

        Args:
            lead_id: The ID of the lead ticket to schedule an appointment for.
            appointment_type: The type of appointment to schedule, must be either ("briefing_call" or "site_visit").
            datetime: The date and time of the appointment in ISO format (e.g. "2025-06-01T10:00:00Z").
            notes: Any additional notes for the appointment.

        Returns:
            A dictionary with the following keys:
            - success: True if the appointment was scheduled successfully, False otherwise.
            - appointment_id: The ID of the appointment if scheduled successfully, None otherwise.
            - error: The error message if the appointment was not scheduled successfully, None if successful.
        """

        return {'success': True, 'appointment_id': '123456', 'error': None}

    @function_tool
    async def create_support_ticket(self, context: RunContext, project_id: str, issue_category: str, summary: str, callback_requested: bool, preferred_time: str):
        """
        Creates a standard support ticket for an existing project query.
        
        Args:
            project_id: The ID of the project to create a support ticket for.
            issue_category: The category of the issue to create a support ticket for,(e.g., 'Status Update', 'Payment Query', 'Delay Concern').
            summary: The summary of the issue to create a support ticket for.
            callback_requested: Whether the customer wants to be called back.
            preferred_time: The preferred time for the callback.

        Returns:
            A dictionary with the following keys:
            - success: True if the support ticket was created successfully, False otherwise.
            - support_ticket_id: The ID of the support ticket if created successfully, None otherwise.
            - error: The error message if the support ticket was not created successfully, None if successful.
        """

        return {'success': True, 'support_ticket_id': '123456', 'error': None}

    @function_tool
    async def create_escalation_ticket(self, context: RunContext, project_id: str, summary: str, customer_sentiment: str):
        """
        Creates a high-priority escalation ticket for a serious customer complaint.

        Args:
            project_id: The ID of the project to create an escalation ticket for.
            summary: A detailed summary of the issue (customer's complaint and demands) to create an escalation ticket for.
            customer_sentiment: The sentiment of the customer (e.g., 'angry', 'frustrated', 'threatening social media post').

        Returns:
            A dictionary with the following keys:
            - success: True if the escalation ticket was created successfully, False otherwise.
            - escalation_ticket_id: The ID of the escalation ticket if created successfully, None otherwise.
            - error: The error message if the escalation ticket was not created successfully, None if successful.
        """

        return {'success': True, 'escalation_ticket_id': '123456', 'error': None}

    @function_tool
    async def update_contact_preferences(self, context: RunContext, phone: str, action: str):
        """
        Updates the contact preferences for a customer by adding or removing them from the contact list.
        
        Args:
            phone: The phone number of the customer to update the contact preferences for.
            action: The action to update the contact preferences for, must be either ("unsubscribe" or "delete_data").

        Returns:
            A dictionary with the following keys:
            - success: True if the contact preferences were updated successfully, False otherwise.
            - error: The error message if the contact preferences were not updated successfully, None if successful.
        """

        return {'success': True, 'error': None}

    ##########################################################################################################################################################################################

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