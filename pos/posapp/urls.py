from django.urls import path
from django.views.generic import RedirectView

from posapp import views

urlpatterns = [
    path('', views.index, name='index'),
    path('waiter', RedirectView.as_view(url='waiter/tabs'), name='waiter'),
    path('waiter/tabs', views.Waiter.Tabs.as_view(), name='waiter/tabs'),
    path('waiter/tabs/<uuid:id>', views.Waiter.Tabs.Tab.as_view(), name='waiter/tabs/tab'),
    path('waiter/orders', views.Waiter.Orders.as_view(), name='waiter/orders'),
    path('manager', RedirectView.as_view(url="manager/users"), name='manager'),
    path('manager/users', views.Manager.Users.as_view(), name='manager/users'),
    path('manager/users/create', views.Manager.Users.Create.as_view(), name='manager/users/create'),
    path('manager/tills', RedirectView.as_view(url="tills/overview"), name='manager/tills'),
    path('manager/tills/overview', views.manager_tills_overview, name='manager/tills/overview'),
    path('manager/tills/assign', views.manager_tills_assign, name='manager/tills/assign'),
    path('manager/tills/till', views.manager_tills_till, name='manager/tills/till'),
    path('manager/tills/till/stop', views.manager_tills_till_stop, name='manager/tills/till/stop'),
    path('manager/tills/till/count', views.manager_tills_till_count, name='manager/tills/till/count'),
    path('manager/tills/till/close', views.manager_tills_till_close, name='manager/tills/till/close'),
    path('manager/tills/till/edit', views.manager_tills_till_edit, name='manager/tills/till/edit'),
    path('admin', RedirectView.as_view(url="admin/finance"), name='admin'),
    path('admin/finance', RedirectView.as_view(url="finance/currencies"), name='admin/finance'),
    path('admin/finance/currencies', views.admin_finance_currencies, name='admin/finance/currencies'),
    path('admin/finance/methods', views.admin_finance_methods, name='admin/finance/methods'),
    path('admin/finance/methods/delete', views.admin_finance_methods_delete, name='admin/finance/methods/delete'),
    path('admin/units', RedirectView.as_view(url="admin/units/overview"), name='admin/units'),
    path('admin/units/overview', views.admin_units_overview, name='admin/units/overview'),
    path('admin/menu', RedirectView.as_view(url="admin/menu/products"), name='admin/menu'),
    path('admin/menu/products', views.Admin.Menu.Products.as_view(), name='admin/menu/products'),
    path('admin/menu/products/<uuid:id>', views.Admin.Menu.Products.Product.as_view(),
         name='admin/menu/products/product'),
    path('admin/menu/products/<uuid:id>/delete', views.Admin.Menu.Products.Product.Delete.as_view(),
         name='admin/menu/products/product/delete'),
]
