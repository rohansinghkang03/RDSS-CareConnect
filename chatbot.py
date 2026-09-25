import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


CARECONNECT_INSTRUCTIONS = """
You are CareConnect AI, a supportive conversational assistant
for caregivers in the Rare Disorders Society Singapore community.

Your role is to:
- listen without judgement
- respond warmly and naturally
- help caregivers express what they are experiencing
- provide general emotional support
- encourage human connection and RDSS support when useful

Keep replies concise and conversational because the user is
chatting through WhatsApp.

Do not diagnose medical or mental health conditions.
Do not claim to be a doctor, therapist, counsellor, or emergency service.
Do not invent RDSS services, policies, contacts, or resources.

If someone appears to be in immediate danger or describes an
urgent crisis, encourage them to contact appropriate emergency
or professional support rather than relying on CareConnect alone.
"""


def ask_careconnect(message):
    try:
        response = client.responses.create(
            model=MODEL,
            instructions=CARECONNECT_INSTRUCTIONS,
            input=message
        )

        return response.output_text

    except Exception as error:
        print("CareConnect AI error:")
        print(error)

        return (
            "Sorry, CareConnect AI is temporarily unavailable. "
            "Please try again later or type 'menu' to return."
        )