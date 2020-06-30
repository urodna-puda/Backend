from django import template
from django.conf import settings

register = template.Library()


@register.filter
def add_one(value):
    try:
        return value + 1
    except TypeError:
        return None


@register.filter
def replace_spaces(value):
    if isinstance(value, str):
        return value.replace(' ', '_')
    else:
        return value


@register.filter
def empty_none(value):
    return value if value else ""


@register.filter
def format_title(value):
    title_suffix = settings.DEFAULT_PAGE_TITLE or "PUDA POS"
    return f"{value} - {title_suffix}" if value else title_suffix
