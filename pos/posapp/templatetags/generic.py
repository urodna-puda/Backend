from django import template

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
