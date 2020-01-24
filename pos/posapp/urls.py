from django.urls import path
from django.views.generic import RedirectView

from posapp import views

urlpatterns = [
    path('', views.index, name='index'),
    path('waiter', RedirectView.as_view(url='tabs'), name='waiter'),
    path('waiter/tabs', views.waiter_tabs, name='waiter/tabs'),
    path('waiter/orders', views.waiter_orders, name='waiter/orders'),
    path('manager', RedirectView.as_view(url="users"), name='manager'),
    path('manager/users', RedirectView.as_view(url="overview"), name='manager/users'),
    path('manager/users/overview', views.manager_users_overview, name='manager/users/overview'),
    path('manager/users/create', views.manager_users_create, name='manager/users/create'),
    path('manager/tills', RedirectView.as_view(url="overview"), name='manager/tills'),
    path('manager/tills/overview', views.manager_tills_overview, name='manager/tills/overview'),
    path('manager/tills/create', views.manager_tills_create, name='manager/tills/create'),
    path('admin', RedirectView.as_view(url="finance"), name='admin'),
    path('admin/finance', RedirectView.as_view(url="currencies"), name='admin/finance'),
    path('admin/finance/currencies', views.admin_finance_currencies, name='admin/finance/currencies'),
    path('admin/finance/methods', views.admin_finance_methods, name='admin/finance/methods'),
]
