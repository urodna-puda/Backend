from django.urls import path
from django.views.generic import RedirectView

from posapp import views

urlpatterns = [
    path('', views.index, name='index'),
    path('waiter/tabs', views.waiter_tabs, name='waiter/tabs'),
    path('waiter/orders', views.waiter_orders, name='waiter/orders'),
    path('manager/waiters', RedirectView.as_view(url="overview"), name='manager/waiters'),
    path('manager/waiters/overview', views.manager_waiters_overview, name='manager/waiters/overview'),
    path('manager/waiters/assign', views.manager_waiters_assign, name='manager/waiters/assign'),
]
