from colors import COLOR_MANAGER_BACKUP
from constants import ORDINAL_WORDS
from data_loader import contrasting_text_color, resolve_manager_name


def manager_pill(manager_id: str, name_resolver: dict[str, str], manager_color_map: dict[str, str], label: str | None = None) -> str:
    """Colored pill (that manager's own color, contrasting text,
    rounded corners) around their resolved display name - "{label}
    ({name})" when a label is given (e.g. pages_matchups.py's "Manager 1
    (Alex F)"), otherwise just the bare name (e.g. pages_drafts.py's
    draft-pick cards)."""
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
