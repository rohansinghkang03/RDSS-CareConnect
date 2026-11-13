from database import get_approved_support_buddies, get_latest_match_request


def find_matches(user):
    buddies = get_approved_support_buddies()
    from basic_profile import enabled,get,language_set
    redesigned=enabled()
    profile=get(user.get('sender')) if redesigned else None
    if redesigned and not profile:return []
    languages=set(profile['chat_languages'].split('|')) if profile else set()
    latest_request = get_latest_match_request(user.get("sender"))
    unavailable_buddy_id = (
        latest_request.get("buddy_id")
        if latest_request and latest_request["status"] == "declined" else None
    )
    results = []

    for buddy in buddies:
        # A person should not be matched with themselves.
        if buddy["sender"] == user.get("sender"):
            continue
        # "Find another buddy" should not immediately suggest the same person.
        if buddy["id"] == unavailable_buddy_id:
            continue

        support_types = {
            item.strip()
            for item in buddy["support_types"].split("|")
            if item.strip()
        }

        availability = {
            item.strip()
            for item in buddy["availability"].split("|")
            if item.strip()
        }

        if redesigned and not languages.intersection(set(language_set(buddy.get('languages') or '').split('|'))):continue
        score = 0
        shared_preferences = []

        if user.get("support_type") in support_types:
            score += 1
            shared_preferences.append("Support: " + user["support_type"])

        preferred_time = user.get("availability")

        if availability and (
            preferred_time in availability
            or "Flexible" in availability
            or preferred_time == "Flexible"
        ):
            score += 1
            if preferred_time == "Flexible":
                shared_preferences.append("Chat times: your flexible schedule fits their availability")
            elif preferred_time in availability:
                shared_preferences.append("Chat times: " + preferred_time)
            else:
                shared_preferences.append("Chat times: " + preferred_time + " fits their flexible availability")

        # Do not recommend someone with no matching preferences.
        if score == 0 and not redesigned:
            continue

        percentage = round((score / 2) * 100)

        results.append({
            "buddy_id": buddy["id"],
            "sender": buddy["sender"],
            "name": buddy["name"],
            "score": score,
            "percentage": percentage,
            "shared_preferences": shared_preferences,
            "tier": 'exact' if score==2 else 'support' if user.get("support_type") in support_types else 'time' if score else 'other',
            'languages':buddy.get('languages',''),
            'contact_methods':(buddy.get('contact_methods') or 'WhatsApp text'),
            'introduction':buddy.get('introduction',''),
            "offered_support": sorted(support_types),
            "offered_times": sorted(availability)
        })

    results.sort(
        key=lambda person: (
            {'exact':0,'support':1,'time':2,'other':3}[person['tier']],
            person["buddy_id"]
        )
    )

    return results
