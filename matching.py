from database import get_caregivers


def find_matches(user):
    caregivers = get_caregivers()

    results = []

    for caregiver in caregivers:
        score = 0

        if caregiver["mood"] == user["mood"]:
            score += 1

        if caregiver["support_type"] == user["support_type"]:
            score += 1

        if (
            caregiver["availability"] == user["availability"]
            or caregiver["availability"] == "Flexible"
            or user["availability"] == "Flexible"
        ):
            score += 1

        percentage = round((score / 3) * 100)

        results.append({
            "name": caregiver["name"],
            "score": score,
            "percentage": percentage
        })

    results.sort(
        key=lambda person: person["score"],
        reverse=True
    )

    return results