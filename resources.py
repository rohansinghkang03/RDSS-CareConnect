def get_resources_menu():
    return """
CareConnect Resource Hub 📚

Looking for information or support?

I can help you explore resources that may be useful
for your caregiving journey.

What would you like help with?

1. RDSS Support
2. Caregiver Support
3. Financial & Social Support
4. Urgent Support

Select a number to explore a category.

Type 'menu' anytime to return to the main menu.
"""


def get_resource_reply(choice):
    resources = {
        "1": """
RDSS Support 💜

Information about RDSS programmes and services
will be available here once verified resources
have been added.

Type 'menu' to return to the main menu.
""",

        "2": """
Caregiver Support 💜

Verified information about caregiving assistance,
respite and other support services will be
available here.

Type 'menu' to return to the main menu.
""",

        "3": """
Financial & Social Support 💜

Verified information about financial assistance
and social support schemes will be available here.

Type 'menu' to return to the main menu.
""",

        "4": """
Urgent Support

If you or someone else is in immediate danger,
contact emergency services immediately.

CareConnect AI and Support Buddy matching
are not emergency support services.

Verified Singapore support contacts will
be added here.

Type 'menu' to return to the main menu.
"""
    }

    return resources.get(
        choice,
        "Please choose 1, 2, 3 or 4. Type 'menu' to return."
    )
