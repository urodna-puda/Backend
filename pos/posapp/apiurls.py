from django.urls import path
from posapp import apiviews

urlpatterns = [
    path('tabs', apiviews.OpenTabs.as_view()),
    path('tabs/all', apiviews.AllTabs.as_view()),
    path('tabs/<uuid:id>/order', apiviews.TabOrder.as_view())
]
