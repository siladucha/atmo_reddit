"""Custom Jinja2 template filters for the RAMP admin panel."""


def humanize_number(value) -> str:
    """Format large numbers into human-readable abbreviated form.

    Logic:
        - < 1000: display as-is
        - 1000–999999: display as "X.YK" (e.g. 1500 → "1.5K")
        - 1000000+: display as "X.YM" (e.g. 6283184 → "6.3M")

    Always rounds to 1 decimal place and strips trailing ".0"
    (e.g. 2000 → "2K" not "2.0K").

    Handles negative numbers by preserving the sign.
    Non-numeric values are returned as-is.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value) if value is not None else ""

    if num == 0:
        return "0"

    sign = "-" if num < 0 else ""
    abs_num = abs(num)

    if abs_num < 1000:
        # Return as integer if it's a whole number, else as-is
        if abs_num == int(abs_num):
            return f"{sign}{int(abs_num)}"
        return f"{sign}{abs_num}"

    if abs_num < 1_000_000:
        formatted = f"{abs_num / 1000:.1f}"
        # Strip trailing ".0"
        if formatted.endswith(".0"):
            formatted = formatted[:-2]
        return f"{sign}{formatted}K"

    # 1,000,000+
    formatted = f"{abs_num / 1_000_000:.1f}"
    # Strip trailing ".0"
    if formatted.endswith(".0"):
        formatted = formatted[:-2]
    return f"{sign}{formatted}M"


def register_filters(env):
    """Register all custom template filters and globals on a Jinja2 environment."""
    env.filters["humanize_number"] = humanize_number

    # UI Observability: register app_env for conditional component markers
    from app.config import get_settings
    if "app_env" not in env.globals:
        env.globals["app_env"] = get_settings().app_env
