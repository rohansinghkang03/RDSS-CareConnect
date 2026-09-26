def get_resources_menu():
    return """
CareConnect Resources

1. RDSS Support
2. Caregiver Support
3. Financial & Social Support
4. Urgent Support

Type 'menu' to return to the main menu.
"""


def get_resource_reply(choice):
    resources = {
        "1": """
RDSS Support

Official RDSS resources and programmes will be added here.

Type 'menu' to return to the main menu.
""",

        "2": """
Caregiver Support

Verified caregiver support resources will be added here.

Type 'menu' to return to the main menu.
""",

        "3": """
Financial & Social Support

Verified financial and social support resources will be added here.

Type 'menu' to return to the main menu.
""",

        "4": """
Urgent Support

If someone is in immediate danger, contact the appropriate emergency services.

Verified Singapore support contacts will be added here.

Type 'menu' to return to the main menu.
"""
    }

    return resources.get(
        choice,
        "Please choose 1, 2, 3 or 4. Type 'menu' to return."
    )