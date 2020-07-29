from django import template

register = template.Library()


@register.simple_tag
def isactive(path, page, exact=False):
    return "active" if (path == ("posapp/" + page) if exact else path.startswith("posapp/" + page)) else ""


@register.simple_tag
def isopen(path, page):
    return "menu-open" if path.startswith("posapp/" + page) else ""
