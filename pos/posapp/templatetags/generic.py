from django import template

register = template.Library()


@register.filter
def add_one(value):
    try:
        return value + 1
    except TypeError:
        return None
