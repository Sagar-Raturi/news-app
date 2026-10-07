import json

from django import template

register = template.Library()


@register.filter
def pretty_json(value):
    """Step output for the activity log, readable and capped."""
    text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    return text if len(text) < 30000 else text[:30000] + "\n…"


@register.filter
def seconds(delta):
    if delta is None:
        return ""
    total = int(delta.total_seconds())
    return f"{total // 60}m {total % 60:02d}s" if total >= 60 else f"{total}s"


@register.filter
def usd(value):
    if value is None:
        return "$0.00"
    return f"${value:.3f}" if value < 1 else f"${value:.2f}"


@register.filter
def tokens(value):
    value = value or 0
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)
