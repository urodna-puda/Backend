from django import template

register = template.Library()


@register.filter
def add_one(value):
    return value + 1


@register.filter
def replace_spaces(value):
    if isinstance(value, str):
        return value.replace(' ', '_')
    else:
        return value


@register.filter
def empty_none(value):
    return value if value else ""
