from django.urls import path, register_converter

from posapp import converters, views

register_converter(converters.ExpenseTransitionConverter, "exp_tr")
register_converter(converters.MembershipTransitionConverter, "mss_tr")

urlpatterns = [path(url, view, name=name) for url, view, name in views.Index.generate_urls()]
