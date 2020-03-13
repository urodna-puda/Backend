from django.urls import path
from posapp import apiviews

urlpatterns = [
    path('tabs', apiviews.OpenTabs.as_view()),
    path('tabs/all', apiviews.AllTabs.as_view()),
    path('tabs/<uuid:id>/order', apiviews.TabOrder.as_view()),
    path('users/<str:username>/toggle/<str:role>', apiviews.UserToggles.as_view()),
    path('users/<str:username>/totp-auth/<int:totp>', apiviews.UserTotpAuth.as_view()),
    path('currencies/<int:id>/toggleEnabled', apiviews.CurrencyToggleEnabled.as_view()),
    path('methods/<uuid:id>/toggleChange', apiviews.MethodToggleChange.as_view()),
    path('products/<uuid:id>/toggleEnabled', apiviews.ProductToggleEnabled.as_view()),
]
