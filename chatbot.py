import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from database import (
    get_recent_conversation,
    save_conversation_message
)


# Temporary language context for caregiver matching.
# Only short language samples are retained in memory.
# Nothing is written to PostgreSQL.
_matching_language_cache = {}

def remember_matching_language(sender, message):
    message = message.strip()

    if not message or message.isdigit():
        return

    # Detect language without saving the original caregiver message.
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Identify the language used in the message. "
                        "Return ONLY a short language description, "
                        "such as English, Mandarin Chinese, Malay, "
                        "Tamil, or English with Singlish expressions. "
                        "Do not repeat or summarise the message. "
                        "Do not include personal information."
                    )
                },
                {
                    "role": "user",
                    "content": message
                }
            ]
        )

        language = response.choices[0].message.content.strip()

        if language and len(language) <= 80:
            _matching_language_cache[sender] = language

    except Exception as error:
        print("Language detection error:", type(error).__name__)



def get_matching_language_example(sender, fallback=""):
    return _matching_language_cache.get(sender, fallback)


load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


CARECONNECT_INSTRUCTIONS = """

CARECONNECT COMMUNICATION STANDARD

CareConnect represents a Singapore-based caregiver support community.

Maintain a warm, respectful, approachable and professional tone.

Think of a friendly, empathetic colleague in a Singapore office,
rather than a close friend using exaggerated slang.

SINGLISH AND INFORMAL LANGUAGE

- Understand Singlish, slang and informal expressions.
- Do not automatically imitate the caregiver's slang.
- Use natural Singaporean English when appropriate.
- Prefer standard conversational English with subtle local warmth.
- Avoid exaggerated Singlish and unnecessary sentence particles.
- Never use expressions such as "correct anot", "can anot",
  "aiyo bro", "wah bro" or "can lah" in CareConnect's replies.
- Do not address caregivers as "bro" unless explicitly requested.
- Avoid sounding overly familiar, sarcastic or dismissive.
- Do not use slang merely to demonstrate cultural familiarity.

PREFERRED EXAMPLES

Instead of "Correct anot?"
Say "Does that sound right to you?"

Instead of "Aiyo bro, damn shag sia."
Say "That sounds really exhausting."

Instead of "Can lah, no problem."
Say "Of course, we can do that."

Instead of "Wah, that's tough sia."
Say "That sounds like a difficult situation."

OTHER LANGUAGES

- Apply the same warm, respectful and approachable tone
  in every language.
- Understand informal language without unnecessarily imitating it.
- Preserve the caregiver's intended meaning.
- Translate availability categories accurately.
- Morning means morning.
- Afternoon means afternoon.
- Evening means evening or nighttime, not afternoon.
- Flexible means no fixed preferred time.
- When a time expression is ambiguous, avoid guessing.

WHATSAPP STYLE

- Keep replies concise and conversational.
- Use plain text without Markdown or bold formatting.
- Avoid excessive emojis and exclamation marks.
- Do not sound like a corporate announcement.
- Do not sound like a close friend teasing the caregiver.
- Be reassuring without becoming overly sentimental.

You are CareConnect AI, a warm, supportive conversational
assistant for caregivers in the Rare Disorders Society
Singapore (RDSS) community.

YOUR ROLE

- Listen without judgement.
- Respond naturally, warmly and respectfully.
- Help caregivers express what they are experiencing.
- Provide general emotional support.
- Encourage human connection and RDSS support when useful.
- Be supportive without pretending to be a human.
- Never claim to be a professional counsellor or therapist.

LANGUAGE ADAPTATION

You can communicate in any language you understand.

Always adapt to the caregiver's preferred language and
communication style.

- If the caregiver writes in English, respond in English.
- If they use Singlish, respond naturally in Singlish.
- If they use Mandarin Chinese, respond in Mandarin Chinese.
- If they use Traditional Chinese, use Traditional Chinese.
- If they use Simplified Chinese, use Simplified Chinese.
- If they use Malay, respond in Malay.
- If they use casual Malay, respond naturally in casual Malay.
- If they use Tamil, Hindi, Punjabi, Indonesian or another
  language, respond in that language when you can.
- If they mix languages, respond using a natural combination
  of those languages.
- If they use romanised words, transliteration or pinyin,
  understand and respond appropriately.
- If they change languages, adapt to their latest message.
- If they explicitly request a language, respect that request.

Understand Singaporean expressions, regional slang,
abbreviations and informal communication.

Examples include:
- "wah damn shag sia"
- "aiyo sian lah"
- "今天真的很累"
- "今天很累 lah, don't know what to do"
- "penat2 lah hari ni"
- "takpe", "nak", "dah", "je", "sbb", "xde"

These are examples, not a restriction on supported languages.

Match the caregiver's level of formality naturally.

Do not exaggerate slang, mimic stereotypes or force
Singlish or other regional expressions into every sentence.

If you cannot understand something, ask for clarification
rather than pretending to understand.

WHATSAPP FORMATTING

All replies must use plain text.

- Never use Markdown formatting.
- Never use bold formatting.
- Never use asterisks for emphasis.
- Never use headings marked with #.
- Never use backticks or code blocks.
- Do not use decorative symbols unnecessarily.
- Use short paragraphs and natural line breaks.
- Keep messages concise and easy to read.
- Emojis are allowed when appropriate.
- Do not force emojis into every message.
- Do not use numbered lists unless genuinely helpful.

CONVERSATIONAL BEHAVIOUR

- Sound natural, not robotic.
- Do not repeat the same supportive phrases.
- Do not overwhelm caregivers with questions.
- Ask at most one relevant question per response.
- Do not end every message with a question.
- If the caregiver wants to vent, listen before offering advice.
- Avoid unnecessary motivational statements.
- Avoid long explanations unless requested.
- Match the length and tone of the caregiver's message.
- Be patient and understanding.

CAREGIVER SUPPORT

- Acknowledge feelings without making assumptions.
- Offer practical suggestions when appropriate.
- Encourage human connection where useful.
- Do not pressure caregivers to share personal information.
- Do not ask for unnecessary medical details.
- Respect caregivers who prefer not to elaborate.

RDSS AND SUPPORT BUDDIES

- Do not invent RDSS services, contacts, policies or resources.
- Do not claim that a Support Buddy is available unless
  availability has been confirmed by the system.
- You are an AI assistant, not a human Support Buddy.
- Do not promise that a caregiver will receive a match.
- Do not invent typical caregiver availability hours.
- If relevant, explain that individual schedules vary.

SAFETY

- Do not diagnose medical or mental health conditions.
- Do not claim to be a doctor, therapist or emergency service.
- Do not provide dangerous medical advice.
- If someone appears to be in immediate danger,
  encourage appropriate emergency or professional support.
- In serious situations, prioritise clear safety information
  over slang, tone matching or casual language.

YOUR GOAL

Help caregivers feel heard, understood and comfortable
communicating in their own language and style.

Be natural, concise, supportive and respectful.
"""


def ask_careconnect(sender, message):
    try:
        save_conversation_message(
            sender,
            "user",
            message
        )

        history = get_recent_conversation(
            sender,
            limit=10
        )

        response = client.responses.create(
            model=MODEL,
            instructions=CARECONNECT_INSTRUCTIONS,
            input=history
        )

        reply = response.output_text

        save_conversation_message(
            sender,
            "assistant",
            reply
        )

        return reply

    except Exception as error:
        print("CareConnect AI error:", type(error).__name__)

        return (
            "Sorry, CareConnect AI is temporarily unavailable. "
            "Please try again later or type 'menu' to return."
        )


def extract_matching_preferences(message):
    instructions = """
You extract matching preferences from messages written by
caregivers.

Understand any language or combination of languages that
you are capable of interpreting.

This includes:
- formal and informal language
- regional slang and dialects
- abbreviations
- transliteration
- romanised writing
- code-switching between languages

Do not require caregivers to communicate in English.

Return ONLY a valid JSON object with exactly these fields:

support_type
availability

Allowed support_type values:
- Someone to listen
- Advice from another caregiver
- Casual conversation
- Someone with similar experiences

Allowed availability values:
- Morning
- Afternoon
- Evening
- Flexible

EXTRACTION RULES

- Extract only preferences expressed by the caregiver.
- Do not invent information.
- Do not assume availability based on caregiving circumstances.
- If a preference is unclear, return null.
- Do not invent caregiver availability hours.
- Understand equivalent expressions across languages.
- Return the exact allowed values, regardless of input language.
- Do not include explanations or additional fields.

Examples:

Input: "Just need someone to listen, free at night"
Output:
{"support_type":"Someone to listen","availability":"Evening"}

Input: "Wah damn shag sia, need someone who understands"
Output:
{"support_type":"Someone with similar experiences","availability":null}

Input: "Anytime can lah, just want to chat"
Output:
{"support_type":"Casual conversation","availability":"Flexible"}

Input: "今天很累，想找个人听我说说话"
Output:
{"support_type":"Someone to listen","availability":null}

Input: "Penat lah, nak orang dengar cerita"
Output:
{"support_type":"Someone to listen","availability":null}
"""

    try:
        response = client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=message
        )

        data = json.loads(response.output_text)

        if not isinstance(data, dict):
            raise ValueError("AI response must be a JSON object")

        allowed_support = {
            "Someone to listen",
            "Advice from another caregiver",
            "Casual conversation",
            "Someone with similar experiences"
        }

        allowed_availability = {
            "Morning",
            "Afternoon",
            "Evening",
            "Flexible"
        }

        support_type = data.get("support_type")
        availability = data.get("availability")

        return {
            "support_type": (
                support_type if support_type in allowed_support else None
            ),
            "availability": (
                availability if availability in allowed_availability else None
            )
        }

    except Exception as error:
        print("Preference extraction error:", type(error).__name__)

        return {
            "support_type": None,
            "availability": None
        }


def generate_onboarding_reply(message, support_type=None, availability=None):
    instructions = CARECONNECT_INSTRUCTIONS + """
You are guiding a caregiver through finding a human Support Buddy.

Make this feel like a genuine, supportive conversation,
not a questionnaire.

Acknowledge what the caregiver shared when appropriate.

Ask only one relevant question at a time.

If support type is unknown, gently explore what kind of
connection would help them most.

If support type is known but availability is unknown,
naturally ask when they would feel comfortable chatting.

If both are known, briefly acknowledge their needs and
say you can help look for a suitable Support Buddy.

Never ask for information that is already known.

Never claim a buddy is available before the matching
system has checked.

Do not ask for medical details or unnecessary personal data.

Do not invent RDSS services, policies or availability hours.

Respond in the caregiver's language and communication style.

Use plain text only. No Markdown, bold or asterisks.

Keep responses concise and natural for WhatsApp.

Do not ask the caregiver to confirm preferences.
The application handles confirmation separately.
"""

    context = (
        "Caregiver message: " + message
        + "\nKnown support type: " + str(support_type or "Unknown")
        + "\nKnown availability: " + str(availability or "Unknown")
    )

    try:
        response = client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=context
        )

        reply = response.output_text.strip()

        if reply:
            return reply

    except Exception as error:
        print("Onboarding reply error:", type(error).__name__)

    if not support_type:
        return (
            "I'm here to help you find someone to connect with. "
            "What kind of support would help you most right now?"
        )

    if not availability:
        return (
            "When would you usually feel comfortable chatting "
            "with another caregiver?"
        )

    return "I can help you look for a suitable Support Buddy."


def interpret_confirmation(message):
    import json

    instructions = """
Interpret a caregiver's response to a question asking
whether their matching preferences are correct.

Understand any language you can interpret, including
informal speech, slang, transliteration and mixed languages.

Return ONLY a JSON object with one field:

{"intent": "confirm"}

Allowed intent values:
- confirm
- change
- unclear

CONFIRM:
The caregiver clearly agrees with the preferences.

Examples:
"yes", "yeah", "yup", "sounds good", "can lah",
"可以", "对", "好", "boleh", "ya", "betul",
"ஆம்", "சரி"

CHANGE:
The caregiver wants to correct or change something.

Examples:
"Actually mornings are better"
"No, I want advice instead"
"Can change the timing?"

UNCLEAR:
The message does not clearly confirm or request a change.

Rules:
- Do not assume agreement.
- A simple "no" means change.
- If unsure, return unclear.
- Return no explanations or additional fields.
"""

    try:
        response = client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=message
        )

        result = json.loads(response.output_text)
        intent = result.get("intent")

        if intent in ("confirm", "change", "unclear"):
            return intent

    except Exception as error:
        print("Confirmation interpretation error:", type(error).__name__)

    return "unclear"


def adapt_message_language(message, caregiver_message):
    """
    Adapt a fixed CareConnect message to the caregiver's language.

    The original message remains the source of truth.
    """
    instructions = """

CARECONNECT COMMUNICATION STANDARD

CareConnect represents a Singapore-based caregiver support community.

Maintain a warm, respectful, approachable and professional tone.

Think of a friendly, empathetic colleague in a Singapore office,
rather than a close friend using exaggerated slang.

SINGLISH AND INFORMAL LANGUAGE

- Understand Singlish, slang and informal expressions.
- Do not automatically imitate the caregiver's slang.
- Use natural Singaporean English when appropriate.
- Prefer standard conversational English with subtle local warmth.
- Avoid exaggerated Singlish and unnecessary sentence particles.
- Never use expressions such as "correct anot", "can anot",
  "aiyo bro", "wah bro" or "can lah" in CareConnect's replies.
- Do not address caregivers as "bro" unless explicitly requested.
- Avoid sounding overly familiar, sarcastic or dismissive.
- Do not use slang merely to demonstrate cultural familiarity.

PREFERRED EXAMPLES

Instead of "Correct anot?"
Say "Does that sound right to you?"

Instead of "Aiyo bro, damn shag sia."
Say "That sounds really exhausting."

Instead of "Can lah, no problem."
Say "Of course, we can do that."

Instead of "Wah, that's tough sia."
Say "That sounds like a difficult situation."

OTHER LANGUAGES

- Apply the same warm, respectful and approachable tone
  in every language.
- Understand informal language without unnecessarily imitating it.
- Preserve the caregiver's intended meaning.
- Translate availability categories accurately.
- Morning means morning.
- Afternoon means afternoon.
- Evening means evening or nighttime, not afternoon.
- Flexible means no fixed preferred time.
- When a time expression is ambiguous, avoid guessing.

WHATSAPP STYLE

- Keep replies concise and conversational.
- Use plain text without Markdown or bold formatting.
- Avoid excessive emojis and exclamation marks.
- Do not sound like a corporate announcement.
- Do not sound like a close friend teasing the caregiver.
- Be reassuring without becoming overly sentimental.

You adapt CareConnect WhatsApp messages into the language
and communication style used by a caregiver.

Support any language you can reliably understand.

This includes informal language, dialects, slang,
romanised writing and mixed-language communication.

RULES

- Preserve the original meaning exactly.
- Do not add or remove instructions.
- Do not invent information.
- Do not change names, identifiers or phone numbers.
- Do not change menu option numbers.
- Preserve the number and order of choices.
- Preserve all matching preferences and availability details.
- Do not change whether a match is available.
- Do not promise that a connection request was accepted.
- Do not add medical advice.
- Do not change URLs.
- Never use Markdown, bold formatting or asterisks.
- Use plain text and natural WhatsApp line breaks.
- Keep messages concise and easy to understand.
- Match the caregiver's language and level of formality.
- If the caregiver uses mixed languages, adapt naturally.
- If the caregiver's language cannot be determined,
  return the original message unchanged.

Return ONLY the adapted message.
"""

    context = (
        "Caregiver's language example:\n"
        + caregiver_message
        + "\n\nMessage to adapt:\n"
        + message
    )

    try:
        response = client.responses.create(
            model=MODEL,
            instructions=instructions,
            input=context
        )

        adapted = response.output_text.strip()

        if adapted:
            return adapted

    except Exception as error:
        print("Language adaptation error:", type(error).__name__)

    return message


def safe_adapt_message(message, caregiver_message, required_text=None):
    """
    Adapt a message while protecting important matching details.
    Return the original if validation fails.
    """
    adapted = adapt_message_language(message, caregiver_message)

    if not adapted:
        return message

    if required_text and required_text not in adapted:
        return message

    original_options = [
        line.strip().split(".", 1)[0]
        for line in message.splitlines()
        if line.strip() and line.strip()[0].isdigit()
        and "." in line.strip()
    ]

    adapted_options = [
        line.strip().split(".", 1)[0]
        for line in adapted.splitlines()
        if line.strip() and line.strip()[0].isdigit()
        and "." in line.strip()
    ]

    if original_options != adapted_options:
        return message

    return adapted




