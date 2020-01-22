from django import template

register = template.Library()


@register.simple_tag
def isactive(path, page):
    return "active" if path.startswith(page) else ""


@register.simple_tag
def isopen(path, page):
    return "menu-open" if path.startswith(page) else ""
