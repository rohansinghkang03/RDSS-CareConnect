from reporting_tracking import feature_call
import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

from database import (
    get_recent_conversation,
    save_conversation_message,
    get_language_preference,
    set_language_preference
)


# Temporary fallback is used only when PostgreSQL is unavailable.
# No caregiver message text is retained in the cache.
_matching_language_cache = {}

# Store only a short, validated language name, never the caregiver's message.
# This is deliberately not a fixed language whitelist.
_LANGUAGE_LABEL = re.compile(r"[A-Za-z][A-Za-z -]{0,79}\Z")

# Brief confirmations are not reliable evidence of a language change.
_SHORT_REPLIES = {
    "yes", "no", "ok", "okay", "sure", "thanks", "thank you", "hi",
    "hello", "bye", "yup", "yeah", "y", "n", "menu", "next",
    "confirm", "cancel", "exit", "back", "continue", "done",
    "好", "对", "是", "不是", "可以", "谢谢", "好的", "嗯",
    "ya", "tak", "boleh", "terima kasih", "சரி", "ஆம்", "இல்லை"
}


def _valid_language_label(value):
    if not isinstance(value, str):
        return False
    if not _LANGUAGE_LABEL.fullmatch(value):
        return False
    # Language labels cannot be whole sentences or caregiver messages.
    return len(value.split()) <= 8


def remember_matching_language(sender, message):
    from conversation_ai import classify,save_style
    if not isinstance(message,str) or not message.strip() or message.strip().isdigit() or message.strip().casefold() in _SHORT_REPLIES:
        return
    result=classify(message,'language_detection',{},allow_choices=False)
    if result and result['language']:
        set_language_preference(sender,result['language'])
        save_style(sender,result['style'])
        _matching_language_cache[sender]=result['language']


def get_matching_language_example(sender, fallback=""):
    try:
        from conversation_ai import canonical_language
        language = canonical_language(get_language_preference(sender))
        if _valid_language_label(language):
            _matching_language_cache[sender] = language
            return language
    except Exception as error:
        print("Language preference read error:", type(error).__name__)
    return _matching_language_cache.get(sender, fallback)


load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=30.0,
    # Avoid hidden billable retries; failures are recorded with unknown usage.
    max_retries=0
)


CARECONNECT_INSTRUCTIONS = """

CARECONNECT COMMUNICATION STANDARD

CareConnect represents a Singapore-based caregiver support community.

Maintain a warm, respectful, approachable and professional tone.

Think of a friendly, empathetic colleague in a Singapore office,
rather than a close friend using exaggerated slang.

SINGLISH AND INFORMAL LANGUAGE

- Match the caregiver's language, formality and natural conversational style.
- If they write informal Malay mixed with English, reply in natural informal
  Singaporean Malay and English. Understand aku, nak, dah, je, takpe, hari2.
- If they use Singlish, respond in natural Singlish, without forced particles.
- Match casual wording without mimicking distress, profanity or stereotypes.
- Do not become overly familiar or address them as bro unless they use it for you.
- Use clear, direct wording for consent, privacy, safety and confirmations.
- Numbers and short acknowledgements preserve the established language/style.

OTHER LANGUAGES

- Apply the same warm, respectful and approachable tone
  in every language.
- Respond naturally in the same informal or formal register as the caregiver.
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
- Help with CareConnect navigation when asked. Valid direct commands are 'menu',
  'resources', 'profile', 'my status', 'application status', 'requests', 'ai chat',
  'language', 'back' and 'help'. Explain the relevant command as a fallback:
  for example, "You can also type 'resources' to open the Resource Hub."
- For an already accepted match, 'my chats' shows available connections; the
  application may offer 'chat ID' and 'stop chat ID'. Direct chat needs separate
  permission from BOTH participants. Never invent phone numbers, wa.me URLs,
  sharing consent, a working button or a sent message. Private buddy conversations
  are outside CareConnect and cannot be read, summarised or monitored by this bot.
- Never invent a screen, command or menu number. Do not claim you opened a screen,
  saved information or sent something; application code performs those actions.
- The application appends verified navigation to your reply. Do not invent an
  alternative footer or omit requested help merely because a footer exists.
- Keep command hints together in the application-provided section headed "You can type these other commands too:".
  Do not scatter generic menu/back/status reminders through your conversational answer.
  When specifically explaining how to open a feature, give its useful command once; the application supplies the remaining shortcuts.
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
- Do not infer that someone is the sole caregiver, cannot sleep, has been doing
  this for years, or lacks help merely because they say they are tired.
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
- Do not claim you saved, noted down, updated or shared a profile/preference.
  The application separately asks for consent and approval before profile saving.
- You can understand requests for profile, menu, resources and status; do not
  invent buttons, saved changes, report results or completed operations.
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


def communication_instructions():
    from conversation_context import current,target
    context=current.get()
    if not context or not context['language']:return ''
    from conversation_script import writing_instructions
    return ('\nEstablished response language and style: '+target()+'. Preserve this on short/neutral replies. Match the latest substantive message when it clearly changes language.\n'
            +writing_instructions(context['language'],context['style']))

def readable_generated_reply(reply,feature='AI Chat'):
    from conversation_context import current
    from conversation_script import script_ok
    context=current.get()
    if not context or script_ok(reply,context['language'],context['style']):return reply
    try:
        response=feature_call(feature,client.responses.create,model=MODEL,store=False,
            instructions=CARECONNECT_INSTRUCTIONS+communication_instructions()+'\nRewrite only the supplied assistant reply in the requested writing system. Preserve its meaning; add no facts. Return only the corrected reply.',
            input=json.dumps({'assistant_reply':reply},ensure_ascii=False))
        repaired=response.output_text
        if isinstance(repaired,str) and repaired.strip() and script_ok(repaired,context['language'],context['style']):return repaired.strip()
    except Exception:pass
    return ("I couldn't write that clearly. Please type 'English', 'Chinese', 'Malay' or 'Tamil', "
            "or tell me which writing style you prefer. Type 'menu' for the main menu.")


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

        response = feature_call('AI Chat', client.responses.create,
            model=MODEL,
            instructions=CARECONNECT_INSTRUCTIONS + communication_instructions(),
            input=history,
            store=False
        )

        reply = response.output_text
        if not isinstance(reply,str) or not reply.strip():
            raise ValueError('Empty AI reply')
        reply=readable_generated_reply(reply)

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
        response = feature_call('Matching preferences', client.responses.create,
            model=MODEL,
            instructions=instructions,
            input=message,
            store=False
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
    instructions = CARECONNECT_INSTRUCTIONS + communication_instructions() + """
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
        response = feature_call('Matching onboarding', client.responses.create,
            model=MODEL,
            instructions=instructions,
            input=context,
            store=False
        )

        reply = response.output_text.strip()

        if reply:
            return readable_generated_reply(reply,'Matching onboarding')

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
        response = feature_call('Confirmation', client.responses.create,
            model=MODEL,
            instructions=instructions,
            input=message,
            store=False
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
    instructions = CARECONNECT_INSTRUCTIONS + """
You adapt FIXED CareConnect interface text. This is translation/presentation, not AI Chat.
The supplied interface text is the source of truth. Preserve every instruction,
privacy warning, condition, negation, status and menu choice. Never add advice,
claims, facts, services, URLs or actions. Never change a name, date or identifier.
Keep every __CC_...__ / __PROFILE_...__ placeholder EXACTLY once, unchanged.
Preserve ALL numbered options in the same order, with the same actions and numbers.
Preserve literal commands such as 'menu', 'profile', 'my status' and 'language'.
Translate ALL notices, validation errors, cancellations, headings and navigation.
Use the requested language/style even when the message being translated is English.
Do not translate text inside protected placeholders. No Markdown/code fences.
Return ONLY the adapted interface text. If unable, return the source unchanged.
"""
    from conversation_context import target
    caregiver_message=target(caregiver_message)
    from conversation_context import current
    from conversation_script import writing_instructions
    turn=current.get()
    instructions+='\n'+writing_instructions(turn['language'] if turn else caregiver_message,turn['style'] if turn else 'standard')

    context = (
        "Caregiver's language example:\n"
        + caregiver_message
        + "\n\nMessage to adapt:\n"
        + message
    )

    try:
        response = feature_call('Translation', client.responses.create,
            model=MODEL,
            instructions=instructions,
            input=context,
            store=False
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
    from conversation_context import current,protect
    context=current.get()
    if context and context['defer']:
        protect(required_text)
        return message
    adapted = adapt_message_language(message, caregiver_message)

    if not adapted:
        return message
    from conversation_script import script_ok
    if context and not script_ok(adapted,context['language'],context['style']):
        return message

    if required_text and required_text not in adapted:
        return message
    markers=re.findall(r'__(?:CC|PROFILE)_[A-Za-z0-9_]+__',message)
    if any(adapted.count(marker)!=message.count(marker) for marker in markers):
        return message
    commands=re.findall(r"'(?:menu|profile|language|status|my status|back|cancel|application status|requests|request [0-9]+|accept [0-9]+|decline [0-9]+)'",message)
    if any(command not in adapted for command in commands):
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




