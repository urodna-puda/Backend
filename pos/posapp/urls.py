from django.urls import path, register_converter

from posapp import converters, views

register_converter(converters.ExpenseTransitionConverter, "exp_tr")
register_converter(converters.MembershipTransitionConverter, "mss_tr")

urlpatterns = [
    path('', views.index, name='index'),
    path('waiter', views.Waiter.as_view(), name='waiter'),
    path('waiter/tabs', views.Waiter.Tabs.as_view(), name='waiter/tabs'),
    path('waiter/tabs/<uuid:id>', views.Waiter.Tabs.Tab.as_view(), name='waiter/tabs/tab'),
    path('waiter/tabs/<uuid:id>/requestTransfer', views.Waiter.Tabs.Tab.RequestTransfer.as_view(),
         name='waiter/tabs/tab/requestTransfer'),
    path('waiter/tabs/<uuid:id>/requestClaim', views.Waiter.Tabs.Tab.RequestClaim.as_view(),
         name='waiter/tabs/tab/requestClaim'),
    path('waiter/tabs/<uuid:id>/changeOwner', views.Waiter.Tabs.Tab.ChangeOwner.as_view(),
         name='waiter/tabs/tab/changeOwner'),
    path('waiter/orders', views.Waiter.Orders.as_view(), name='waiter/orders'),
    path('waiter/orders/<uuid:id>', views.Waiter.Orders.Order.as_view(), name='waiter/orders/order'),
    path('waiter/orders/<uuid:id>/bump/<int:count>', views.Waiter.Orders.Order.Bump.as_view(),
         name='waiter/orders/order/bump'),
    path('waiter/orders/<uuid:id>/requestVoid', views.Waiter.Orders.Order.RequestVoid.as_view(),
         name='waiter/orders/order/requestVoid'),
    path('waiter/orders/<uuid:id>/void', views.Waiter.Orders.Order.Void.as_view(), name='waiter/orders/order/void'),
    path('waiter/orders/<uuid:id>/authenticateAndVoid', views.Waiter.Orders.Order.AuthenticateAndVoid.as_view(),
         name='waiter/orders/order/authenticateAndVoid'),
    path('waiter/direct', views.Waiter.Direct.as_view(), name='waiter/direct'),
    path('waiter/direct/new', views.Waiter.Direct.New.as_view(), name='waiter/direct/new'),
    path('waiter/direct/order', views.Waiter.Direct.Order.as_view(), name='waiter/direct/order'),
    path('waiter/direct/pay', views.Waiter.Direct.Pay.as_view(), name='waiter/direct/pay'),
    path('manager', views.Manager.as_view(), name='manager'),
    path('manager/users', views.Manager.Users.as_view(), name='manager/users'),
    path('manager/users/create', views.Manager.Users.Create.as_view(), name='manager/users/create'),
    path('manager/users/<str:username>', views.Manager.Users.User.as_view(), name='manager/users/user'),
    path('manager/tills', views.Manager.Tills.as_view(), name='manager/tills'),
    path('manager/tills/assign', views.Manager.Tills.Assign.as_view(), name='manager/tills/assign'),
    path('manager/tills/<uuid:id>', views.Manager.Tills.Till.as_view(), name='manager/tills/till'),
    path('manager/tills/<uuid:id>/stop', views.Manager.Tills.Till.Stop.as_view(), name='manager/tills/till/stop'),
    path('manager/tills/<uuid:id>/count', views.Manager.Tills.Till.Count.as_view(), name='manager/tills/till/count'),
    path('manager/tills/<uuid:id>/close', views.Manager.Tills.Till.Close.as_view(), name='manager/tills/till/close'),
    path('manager/tills/<uuid:id>/edit', views.Manager.Tills.Till.Edit.as_view(), name='manager/tills/till/edit'),
    path('manager/requests', views.Manager.Requests.as_view(), name='manager/requests'),
    path('manager/requests/void', views.Manager.Requests.Void.as_view(), name='manager/requests/void'),
    path('manager/requests/void/<uuid:id>/<str:resolution>', views.Manager.Requests.Void.Resolve.as_view(),
         name='manager/requests/void/request/resolve'),
    path('manager/requests/transfer', views.Manager.Requests.Transfer.as_view(), name='manager/requests/transfer'),
    path('manager/requests/transfer/<uuid:id>/<str:resolution>', views.Manager.Requests.Transfer.Resolve.as_view(),
         name='manager/requests/transfer/request/resolve'),
    path('manager/expenses', views.Manager.Expenses.as_view(), name='manager/expenses'),
    path('manager/expenses/create', views.Manager.Expenses.Expense.as_view(), name='manager/expenses/create'),
    path('manager/expenses/<uuid:id>', views.Manager.Expenses.Expense.as_view(), name='manager/expenses/expense'),
    path('manager/expenses/<uuid:id>/invoice_file', views.Manager.Expenses.Expense.InvoiceFile.as_view(),
         name='manager/expenses/expense/invoice_file'),
    path(r'manager/expenses/<uuid:id>/<exp_tr:transition>',
         views.Manager.Expenses.Expense.Transition.as_view(), name='manager/expenses/expense/transition'),
    path('director', views.Director.as_view(), name='director'),
    path('director/finance', views.Director.Finance.as_view(), name='director/finance'),
    path('director/finance/currencies', views.Director.Finance.Currencies.as_view(),
         name='director/finance/currencies'),
    path('director/finance/methods', views.Director.Finance.Methods.as_view(), name='director/finance/methods'),
    path('director/finance/methods/<uuid:id>', views.Director.Finance.Methods.Method.as_view(),
         name='director/finance/method/method'),
    path('director/finance/methods/<uuid:id>/delete', views.Director.Finance.Methods.Method.Delete.as_view(),
         name='director/finance/methods/method/delete'),
    path('director/finance/deposits', views.Director.Finance.Deposits.as_view(), name='director/finance/deposits'),
    path('director/finance/deposits/<uuid:id>', views.Director.Finance.Deposits.Edit.as_view(),
         name='director/finance/deposits/deposit'),
    path('director/finance/deposits/create', views.Director.Finance.Deposits.Edit.as_view(),
         name='director/finance/deposits/create'),
    path('director/units', views.Director.Units.as_view(), name='director/units'),
    path('director/menu', views.Director.Menu.as_view(), name='director/menu'),
    path('director/menu/products', views.Director.Menu.Products.as_view(), name='director/menu/products'),
    path('director/menu/products/<uuid:id>', views.Director.Menu.Products.Product.as_view(),
         name='director/menu/products/product'),
    path('director/menu/products/<uuid:id>/delete', views.Director.Menu.Products.Product.Delete.as_view(),
         name='director/menu/products/product/delete'),
    path('director/menu/items', views.Director.Menu.Items.as_view(), name='director/menu/items'),
    path('director/menu/items/<uuid:id>', views.Director.Menu.Items.Item.as_view(),
         name='director/menu/items/item'),
    path('director/menu/items/<uuid:id>/delete', views.Director.Menu.Items.Item.Delete.as_view(),
         name='director/menu/items/item/delete'),
    path('director/members', views.Director.Members.as_view(), name='director/members'),
    path('director/members/create', views.Director.Members.Member.as_view(), name='director/members/create'),
    path('director/members/<uuid:id>', views.Director.Members.Member.as_view(), name='director/members/member'),
    path('director/members/<uuid:id>/<mss_tr:transition>', views.Director.Members.Member.MembershipTransition.as_view(),
         name='director/members/member/membership'),
    path('debug/createUser', views.Debug.CreateUser.as_view(), name="debug/createUser"),
]
