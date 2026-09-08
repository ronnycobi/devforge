from django import template

from apps.dashboard.labels import friendly_step

register = template.Library()


@register.filter
def friendly(value):
    """Render an internal step/agent key as a customer-facing outcome phrase."""
    return friendly_step(value)
