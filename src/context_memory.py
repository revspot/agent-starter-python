# CONTEXT_MEMORY = """
# Lead Status: Partially qualified. Initial key details (date, guest count, event type, venue type, venue duration) have been gathered, but further information is still needed to fully qualify the lead.
# Key Entities:
#     no_of_events: 3 (Haldi, Mehendi, Reception)
#     no_of_guests: 100
#     wedding_date: June 12th
#     venue_details: Resort, 36 hours
#     budget: Not discussed
#     location_preference: Not discussed
# Next Action: Reconnect with the user later as agreed to ask about their budget for the events and if they have any specific location preferences or other requirements for the resort venue.
# """
CONTEXT_MEMORY = """
Lead Status: Partially qualified. Initial key details (date, guest count, event type, venue type, venue duration) have been gathered, but further information is still needed to fully qualify the lead.
Key Entities:
    no_of_events: 3 (Haldi, Mehendi, Reception)
    no_of_guests: 100
    wedding_date: June 12th
    venue_details: Resort, 36 hours
    budget: Not discussed
    location_preference: Not discussed
Next Action: Reconnect with the user later as agreed to ask about their budget for the events and if they have any specific location preferences or other requirements for the resort venue.
"""

# CONTEXT_MEMORY = """
# <lead_status>The user initiated contact regarding event venues in Bangalore. You successfully gathered key details for their wedding planning needs. The user is planning a Haldi, Mehendi, and Reception for approximately 100 guests on June 12th and requires a resort venue for 36 hours. The conversation was interrupted before discussing specific venue options or budget.</lead_status>
# <next_action>You should reconnect with the user to present suitable resort options based on the gathered requirements and inquire about their budget.</next_action>
# <key_entities>
# no_of_events: 3 (Haldi, Mehendi, Reception)
# no_of_guests: 100
# wedding_date: June 12th
# venue_details: Resort, 36 hours
# budget: Not gathered
# </key_entities>
# """

# CONTEXT_MEMORY="""
# """


# You are provided a memory of the conversation history.
#     conversation_history: {{conversation_history}}
#     If the conversation history is not provided, or is empty, you are starting a new conversation, goto SECTION 1.
#     If the conversation history is provided, you are continuing a previous conversation.
#     "Hi {{lead_honorific}}, this is Deepika from Meragi Celebrations."
#     "We had discussed about wedding planning services in the previous conversation, can we discuss a few more details and finalize the plan?"
#     Go to SECTION 2 to capture any missing details.

# CONTEXT_MEMORY = """
# <context_memory>
# <lead_intent>The user inquired about event venues in Bangalore for a wedding.</lead_intent>
# <completed_actions>You have confirmed the user is planning a wedding with three events (Haldi, Mehendi, Reception) for approximately 100 guests on June 12th. You also gathered that they require the venue for 36 hours and are leaning towards a resort.</completed_actions>
# <lead_status>Partially qualified. Initial key details (date, guest count, event type, venue type, venue duration) have been gathered, but further information is still needed to fully qualify the lead.</lead_status>
# <next_action>You need to reconnect with the user later as agreed. When you reconnect, your next step should be to ask about their budget for the events and if they have any specific location preferences or other requirements for the resort venue.</next_action>
# <key_entities>
# no_of_events: 3 (Haldi, Mehendi, Reception)
# no_of_guests: 100
# wedding_date: June 12th
# venue_details: Resort, 36 hours
# budget: Not discussed
# </key_entities>
# </context_memory>
# """
