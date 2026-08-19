from constants import ORDINAL_WORDS


def ordinal_word(n: int) -> str:
    if 0 <= n < len(ORDINAL_WORDS):
        return ORDINAL_WORDS[n]
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def return_plural(check, singular, plural) -> str:
    return singular if check == 1 else plural


def return_s(check):
    return "s" if check != 1 else ""
