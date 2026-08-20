from colors import COLOR_MANAGER_BACKUP
from constants import ORDINAL_WORDS
from data_loader import contrasting_text_color, resolve_manager_name


def manager_pill(manager_id: str, name_resolver: dict[str, str], manager_color_map: dict[str, str], label: str | None = None) -> str:
    name = resolve_manager_name(manager_id, name_resolver)
    text = f"{label} ({name})" if label else name
    background_color = manager_color_map.get(manager_id, COLOR_MANAGER_BACKUP)
    text_color = contrasting_text_color(background_color)
    return f"<span style='background-color:{background_color}; color:{text_color}; padding:2px 8px; border-radius:6px; font-weight:600; white-space:nowrap;'>{text}</span>"


def ordinal_word(n: int) -> str:
    if 0 <= n < len(ORDINAL_WORDS):
        return ORDINAL_WORDS[n]
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def return_plural(check, singular, plural) -> str:
    return singular if check == 1 else plural


def return_s(check):
    return "s" if check != 1 else ""


def check_keeper_pick_criteria(pick):
    is_snake_era_keeper = pick["draft_type"] == "snake" and pick["overall_pick"] <= pick["num_teams"]
    is_auction_era_keeper = pick["draft_type"] == "auction" and pick["auction_amount"] is None
    return is_snake_era_keeper or is_auction_era_keeper


# get picks from auction era with auction value
def check_auction_pick_criteria(pick):
    return pick["draft_type"] == "auction" and pick["auction_amount"] is not None
