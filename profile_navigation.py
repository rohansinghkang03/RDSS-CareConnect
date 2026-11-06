"""Visible profile navigation; translate instructions, never saved caregiver text."""
import logging
import re

from database import update_user
import phase2_analytics as profiles
from profile_suggestions import PROFILE_FIELD_LABELS, generate_and_prepare_profile_review
from profile_validation import is_safe_profile_value

PROFILE_STATES = {'profile_menu', 'profiling_consent', 'profile_review',
                  'profile_review_edit', 'profile_review_confirm', 'profile_withdraw_confirm'}


def profile_text(sender, template, values=None):
    from handlers import caregiver_message, get_matching_language_example
    from profile_localization import MALAY_LANGUAGES, malay_profile_template
    values = values or {}
    # Only the fixed template reaches the translation service.
    language = (get_matching_language_example(sender) or '').strip().casefold()
    translated = malay_profile_template(template) if language in MALAY_LANGUAGES else None
    if translated is None:
        translated = caregiver_message(sender, template)
    commands = re.findall(r"'(menu|profile)'", template)
    if (not isinstance(translated, str)
            or any(translated.count(key) != 1 for key in values)
            or any(not re.search(r"(?<!\w)" + re.escape(command) + r"(?!\w)", translated, re.IGNORECASE) for command in commands)):
        translated = template
    if values:
        pattern = '|'.join(re.escape(key) for key in values)
        translated = re.sub(pattern, lambda match: values[match.group()], translated)
    return translated


def show_profile(sender, notice=None):
    snapshot = profiles.get_profile_snapshot(sender)
    update_user(sender, state='profile_menu')
    status = {'granted': 'Enabled', 'declined': 'Disabled (declined)',
              'withdrawn': 'Disabled (withdrawn)', 'not_given': 'Not enabled'}[snapshot['consent']]
    template = 'My caregiver profile 💜\n\nProfile suggestions: ' + status + '\n'
    values = {}
    if snapshot['fields']:
        template += '\nSaved profile information:\n'
        for field, label in PROFILE_FIELD_LABELS.items():
            if field in snapshot['fields']:
                marker = '__PROFILE_' + field.upper() + '__'
                template += label + ': ' + marker + '\n'
                values[marker] = snapshot['fields'][field]
    else:
        template += '\nNo profile information is saved.\n'
    template += (
        '\nYour profile is private and is not shared with other caregivers by this feature.\n\n'
        '1. Review profile suggestions\n'
        '2. Enable suggestions / read permission details\n'
        '3. Withdraw permission and delete my profile\n'
        '4. Return to main menu\n'
        '5. Continue AI Chat\n\n'
        "Choose a number. Type 'menu' anytime for the main menu."
    )
    if notice:
        template = notice + '\n\n' + template
    return profile_text(sender, template, values)


def consent_prompt(sender):
    from handlers import PROFILING_CONSENT_PROMPT
    update_user(sender, state='profiling_consent')
    return profile_text(sender, PROFILING_CONSENT_PROMPT)


def suggestion_message(sender, suggestion):
    field = suggestion['field_name']
    if field not in PROFILE_FIELD_LABELS or not is_safe_profile_value(suggestion['proposed_value']):
        raise ValueError('Invalid profile suggestion')
    return profile_text(sender,
        'CareConnect AI Profile 💜\n\nSuggested ' + PROFILE_FIELD_LABELS[field].lower() + ':\n'
        '__PROFILE_VALUE__\n\nDoes this describe your situation accurately?\n\n'
        '1. Accept suggestion\n2. Edit suggestion\n3. Reject suggestion\n\n'
        "Type 'profile' to view your saved information or withdraw permission.\n"
        "Type 'menu' for the main menu.",
        {'__PROFILE_VALUE__': suggestion['proposed_value']})


def edited_message(sender, value):
    return profile_text(sender,
        'CareConnect AI Profile 💜\n\nYour edited suggestion:\n__PROFILE_VALUE__\n\n'
        'Would you like to save this exact wording?\n\n'
        '1. Confirm and save\n2. Cancel edit\n\n'
        "Type 'profile' to view your profile or withdraw permission.\n"
        "Type 'menu' for the main menu.", {'__PROFILE_VALUE__': value})


def review(sender):
    try:
        result = generate_and_prepare_profile_review(sender)
    except PermissionError:
        return show_profile(sender, 'Your permission changed. Choose an option below to continue.')
    except ValueError:
        return show_profile(sender, 'There is not enough eligible information for a suggestion yet. Choose 5 to continue AI Chat, then return here to review.')
    except Exception:
        logging.getLogger(__name__).warning('Profile suggestion review temporarily unavailable')
        return show_profile(sender, 'Profile suggestions are temporarily unavailable. Please try again later.')
    if result['status'] == 'pending':
        update_user(sender, state='profile_review')
        return suggestion_message(sender, result['suggestion'])
    return show_profile(sender, result['message'])


def withdraw(sender):
    profiles.withdraw_profiling_consent(sender)
    return show_profile(sender,
        'Your permission for AI-assisted caregiver profiling has been withdrawn. 💜\n'
        'Your saved caregiver profile information, suggestions and unfinished edits have been deleted.\n'
        'Your AI chat history is separate and has not been deleted.')


def handle_profile_navigation(sender, text, state, original_text):
    if text in ('profile', 'my profile') or (state == 'main_menu' and text == '6'):
        return show_profile(sender)
    if text == 'withdraw profile consent':
        # This explicit legacy command remains supported; numbered withdrawal asks for confirmation.
        return withdraw(sender)
    if text == 'review profile':
        if profiles.get_profiling_consent(sender) != 'granted':
            return consent_prompt(sender)
        return review(sender)
    if state not in PROFILE_STATES or text in ('menu', 'language', 'status', 'application status', 'my status'):
        return None

    if state == 'profile_menu':
        if text == '1':
            if profiles.get_profiling_consent(sender) != 'granted':
                return consent_prompt(sender)
            return review(sender)
        if text == '2':
            return consent_prompt(sender)
        if text == '3':
            update_user(sender, state='profile_withdraw_confirm')
            return profile_text(sender,
                'Withdraw profile permission?\n\nThis deletes your saved profile, suggestions and unfinished edits. '
                'AI chat history is separate and will remain. You can continue using AI Chat.\n\n'
                '1. Yes, withdraw permission and delete my profile\n2. Cancel and keep my profile\n\n'
                "Type 'menu' for the main menu.")
        if text == '4':
            from handlers import show_careconnect_menu
            update_user(sender, state='main_menu')
            return show_careconnect_menu(sender)
        if text == '5':
            update_user(sender, state='ai_chat')
            return profile_text(sender,
                "You're chatting with CareConnect AI. 💜\n\nWhat's on your mind?\n\n"
                "Type 'menu' and choose 6 to view your profile, review suggestions or withdraw permission.")
        return show_profile(sender, 'Please choose an option below.')

    if state == 'profiling_consent':
        if text == '1':
            if profiles.get_profiling_consent(sender) != 'granted':
                profiles.grant_profiling_consent(sender)
            return show_profile(sender,
                'Your permission for AI-assisted profile suggestions has been recorded. 💜\n'
                'Choose 5 to continue AI Chat. Only messages sent after you enabled permission are eligible. '
                'Return here and choose 1 when you want to review a suggestion.')
        if text == '2':
            profiles.decline_profiling_consent(sender)
            return show_profile(sender, 'Profile suggestions are disabled. Any previously saved profiling information has been deleted.')
        return consent_prompt(sender)

    if state == 'profile_withdraw_confirm':
        if text == '1':
            return withdraw(sender)
        if text == '2':
            return show_profile(sender, 'Withdrawal cancelled. Your profile permission and saved information are unchanged.')
        return profile_text(sender, '1. Withdraw permission and delete my profile\n2. Cancel and keep my profile')

    pending = profiles.get_pending_profile_suggestion(sender)
    if pending is None:
        return show_profile(sender, 'No pending suggestion is available. Review a new suggestion from the options below.')
    if state == 'profile_review':
        if text == '1':
            profiles.review_profile_suggestion(sender, pending['id'], True)
            from handlers import track_usage_safely
            track_usage_safely(sender, 'profile_suggestion_reviewed')
            return show_profile(sender, 'Your suggestion has been added to your caregiver profile. 💜')
        if text == '2':
            update_user(sender, state='profile_review_edit')
            return profile_text(sender,
                'Please type the corrected profile information.\n\n'
                'It will only be saved after you confirm the exact wording. '
                'Leave out names, contact details and identifying information.\n\n'
                "Type 'profile' to return to your profile, or 'menu' for the main menu.")
        if text == '3':
            profiles.review_profile_suggestion(sender, pending['id'], False)
            from handlers import track_usage_safely
            track_usage_safely(sender, 'profile_suggestion_reviewed')
            return show_profile(sender, 'Suggestion rejected. Nothing was added to your profile. 💜')
        return suggestion_message(sender, pending)
    if state == 'profile_review_edit':
        if not is_safe_profile_value(original_text):
            return profile_text(sender,
                'Please enter a shorter description without contact details or identifying information. '
                "Type 'profile' to return to your profile.")
        profiles.save_pending_profile_edit(sender, pending['id'], original_text)
        update_user(sender, state='profile_review_confirm')
        return edited_message(sender, original_text.strip())
    if state == 'profile_review_confirm':
        if text == '1':
            profiles.confirm_pending_profile_edit(sender, pending['id'])
            from handlers import track_usage_safely
            track_usage_safely(sender, 'profile_suggestion_reviewed')
            return show_profile(sender, 'Your edited profile information has been saved. 💜')
        if text == '2':
            profiles.cancel_pending_profile_edit(sender, pending['id'])
            update_user(sender, state='profile_review')
            return suggestion_message(sender, pending)
        edited = profiles.get_pending_profile_edit(sender, pending['id'])
        if edited is None:
            update_user(sender, state='profile_review')
            return suggestion_message(sender, pending)
        return edited_message(sender, edited)
    return None
