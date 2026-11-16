from datetime import date


def age_on(birth_date: date, today: date) -> int:
    return (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )


def validate_birth_date(value: date, today: date) -> date:
    age = age_on(value, today)
    if age < 18:
        raise ValueError("must_be_18_or_older")
    if age > 100:
        raise ValueError("birth_date_invalid")
    return value


def validate_alias(value: str) -> str:
    value = value.strip()
    if not 2 <= len(value) <= 40 or any(
        ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value
    ):
        raise ValueError("alias_invalid")
    return value


def validate_target_genders(value: list[str]) -> list[str]:
    allowed = {"M", "W", "NB", "ALL"}
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 3
        or any(not isinstance(item, str) or item not in allowed for item in value)
        or len(set(value)) != len(value)
        or ("ALL" in value and len(value) != 1)
    ):
        raise ValueError("target_genders_invalid")
    return list(value)


def validate_age_preferences(minimum: int, maximum: int) -> None:
    if type(minimum) is not int or type(maximum) is not int or not 18 <= minimum <= maximum <= 100:
        raise ValueError("age_preference_range_invalid")


def validate_distance_preference(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 50:
        raise ValueError("distance_preference_range_invalid")
