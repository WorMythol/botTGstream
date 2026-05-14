"""Jinja2-based notification message template rendering."""
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


def _format_viewers(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


_jinja_env.filters["format_viewers"] = _format_viewers


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
    context = {
        "streamer_name": streamer_name,
        "stream_title": stream_title or "",
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
