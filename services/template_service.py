"""Jinja2-based notification message template rendering.

Templates are rendered for Telegram Markdown v1. External API content (stream titles,
usernames) is sanitised via `md_escape` before insertion to avoid parse errors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import structlog
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError

logger = structlog.get_logger(__name__)

DEFAULT_TEMPLATE = """\
🔴 *{{ streamer_name }}* is LIVE!

{% if stream_title %}📺 {{ stream_title }}{% endif %}
{% if viewer_count %}👥 {{ viewer_count | format_viewers }} viewers{% endif %}

Watch now:
{% for link in platform_links %}▶️ [{{ link.platform | title }}]({{ link.url }})
{% endfor %}"""

_jinja_env = Environment(undefined=StrictUndefined, autoescape=False)

# FIX M-5: Telegram Markdown v1 special chars that break parsing when unescaped
_MD_SPECIAL = str.maketrans({
    "*": r"\*",
    "_": r"\_",
    "`": r"\`",
    "[": r"\[",
})


def md_escape(text: str) -> str:
    """Escape Markdown v1 special characters in user-controlled / API-sourced strings."""
    return text.translate(_MD_SPECIAL) if text else text


def _format_viewers(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


_jinja_env.filters["format_viewers"] = _format_viewers
_jinja_env.filters["md_escape"] = md_escape


@dataclass
class PlatformLink:
    platform: str
    url: str


def validate_template(template_str: str) -> Optional[str]:
    """Return error message if template is invalid, else None."""
    try:
        _jinja_env.parse(template_str)
        return None
    except TemplateSyntaxError as exc:
        return str(exc)


def render_template(
    template_str: Optional[str],
    streamer_name: str,
    stream_title: Optional[str],
    viewer_count: Optional[int],
    platform_links: List[PlatformLink],
) -> str:
    """Render a notification message from a Jinja2 template.

    Falls back to DEFAULT_TEMPLATE if template_str is None or rendering fails.
    """
    src = template_str or DEFAULT_TEMPLATE
    # FIX M-5: escape API-sourced strings before rendering into Markdown v1
    context = {
        "streamer_name": md_escape(streamer_name),
        "stream_title": md_escape(stream_title or ""),
        "viewer_count": viewer_count,
        "platform_links": platform_links,
    }
    try:
        tmpl = _jinja_env.from_string(src)
        return tmpl.render(**context).strip()
    except (TemplateSyntaxError, UndefinedError) as exc:
        logger.warning("template.render_failed", error=str(exc))
        # Fallback to default
        tmpl = _jinja_env.from_string(DEFAULT_TEMPLATE)
        return tmpl.render(**context).strip()
