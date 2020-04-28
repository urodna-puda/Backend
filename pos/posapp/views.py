import decimal
import uuid

# Create your views here.
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django import views
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q, ProtectedError
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect
from django.urls import reverse

from posapp.forms import CreateUserForm, CreatePaymentMethodForm, CreateEditProductForm, ItemsInProductFormSet, \
    CreateItemForm, AuthenticationForm, CreateEditDepositForm
from posapp.models import Tab, ProductInTab, Product, User, Currency, Till, Deposit, TillMoneyCount, \
    PaymentInTab, PaymentMethod, UnitGroup, Unit, ItemInProduct, Item, OrderVoidRequest, TabTransferRequest
from posapp.security.role_decorators import WaiterLoginRequiredMixin, ManagerLoginRequiredMixin, \
    DirectorLoginRequiredMixin


class Notification:
    def __init__(self, count, title, icon, link):
        self.count = count
        self.title = title
        self.icon = icon
        self.link = link


class Notifications(list):
    def __init__(self):
        super(Notifications, self).__init__()

    @property
    def total(self):
        return sum(n.count for n in self)

    @property
    def header(self):
        total = self.total
        return "1 Notification" if total == 1 else f"{total} Notifications"


class Context:
    def __init__(self, request, template_name):
        self.page = request.get_full_path()[1:]
        self.waiter_role = request.user.is_waiter
        self.manager_role = request.user.is_manager
        self.director_role = request.user.is_director
        self.notifications = Notifications()
        self.version = settings.VERSION
        self.data = {}
        self.request = request
        self.template_name = template_name

        if self.manager_role:
            unresolved_requests = OrderVoidRequest.objects.filter(resolution__isnull=True)
            count = len(unresolved_requests)
            if count == 1:
                self.notifications.append(
                    Notification(count, "1 Void request", "trash", reverse("manager/requests/void"))
                )
            elif count > 1:
                self.notifications.append(
                    Notification(count, f"{count} void requests", "trash", reverse("manager/requests/void"))
                )

            unresolved_requests = TabTransferRequest.objects.all()
            count = len(unresolved_requests)
            if count == 1:
                self.notifications.append(
                    Notification(count, "1 Tab transfer request", "people-arrows", reverse("manager/requests"))
                )
            elif count > 1:
                self.notifications.append(
                    Notification(count, f"{count} Tab transfer requests", "people-arrows", reverse("manager/requests"))
                )

    def add_pagination_context(self, manager, key, page_get_name="page", page_length_get_name="page_length"):
        count = manager.count()
        page_length = int(self.request.GET.get(page_length_get_name, 20))
        page = int(self.request.GET.get(page_get_name, 0))

        last_page = count // page_length

        page = min(page, last_page)

        if page < (last_page / 2):
            first_link = max(0, page - 2)
            start = first_link
            end = min(last_page + 1, first_link + 5)
        else:
            last_link = min(last_page, page + 2) + 1
            start = max(0, last_link - 5)
            end = last_link

        self[key] = {
            "data": manager[page * page_length:(page + 1) * page_length],
            "showing": {
                "from": page * page_length,
                "to": min((page + 1) * page_length - 1, count - 1),
                "of": count,
            },
            "pages": {
                'previous': page - 1,
                'showPrevious': (page - 1) >= 0,
                'next': page + 1,
                'showNext': (page + 1) <= last_page,
                'last': last_page,
                'page': page,
                'page_length': {
                    "options": [5, 10, 20, 50, 100, 200, 500],
                    "value": page_length,
                },
                "links": [{'page': i, 'active': i == page} for i in range(start, end)],
            },
        }

        if page_length not in self[key]["pages"]["page_length"]["options"]:
            self[key]["pages"]["page_length"]["options"].append(page_length)

    def render(self, content_type=None, status=None, using=None):
        return render(self.request, self.template_name, dict(self), content_type, status, using)

    def __getitem__(self, item):
        return self.data[item]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __len__(self):
        return 6 + len(self.data)

    def __contains__(self, item):
        return item in self.data

    def __iter__(self):
        yield 'page', self.page
        yield 'waiter_role', self.waiter_role
        yield 'manager_role', self.manager_role
        yield 'director_role', self.director_role
        yield 'notifications', self.notifications
        yield 'version', self.version
        for key in self.data:
            yield key, self.data[key]


def check_dict(dictionary, keys):
    for key in keys:
        if key not in dictionary:
            return False
    return True


def prepare_tab_dict(tab):
    variance = tab.variance
    out = {
        'name': tab.name,
        'id': tab.id,
        'total': tab.total,
        'paid': tab.paid,
        'owner': tab.owner,
        'variance': abs(variance),
        'showVariance': variance != 0,
        'varianceLabel': 'To pay' if variance > 0 else 'To change',
        'showFinaliseAuto': variance == 0,
        'showFinaliseChange': variance < 0,
        'products': []
    }

    order_list = ProductInTab.objects.filter(tab=tab)
    products = {}
    for order in order_list:
        if order.product.id not in products:
            products[order.product.id] = {
                'id': order.product.id,
                'name': order.product.name,
                'variants': {},
            }

        if order.note not in products[order.product.id]['variants']:
            products[order.product.id]['variants'][order.note] = {
                'note': order.note,
                'orderedCount': 0,
                'preparingCount': 0,
                'toServeCount': 0,
                'servedCount': 0,
                'showOrdered': False,
                'showPreparing': False,
                'showToServe': False,
                'showServed': False,
                'total': 0,
                'orders': [],
            }

        if order.state == ProductInTab.ORDERED:
            products[order.product.id]['variants'][order.note]['orderedCount'] += 1
            products[order.product.id]['variants'][order.note]['showOrdered'] = True
        elif order.state == ProductInTab.PREPARING:
            products[order.product.id]['variants'][order.note]['preparingCount'] += 1
            products[order.product.id]['variants'][order.note]['showPreparing'] = True
        elif order.state == ProductInTab.TO_SERVE:
            products[order.product.id]['variants'][order.note]['toServeCount'] += 1
            products[order.product.id]['variants'][order.note]['showToServe'] = True
        elif order.state == ProductInTab.SERVED:
            products[order.product.id]['variants'][order.note]['servedCount'] += 1
            products[order.product.id]['variants'][order.note]['showServed'] = True

        products[order.product.id]['variants'][order.note]['orders'].append(order)
        products[order.product.id]['variants'][order.note]['total'] += order.price

    for product_id in products:
        variants = []
        for variant in products[product_id]['variants']:
            variants.append(products[product_id]['variants'][variant])

        out['products'].append({
            'id': products[product_id]['id'],
            'name': products[product_id]['name'],
            'variants': variants,
        })

    return out


@login_required
def index(request):
    return redirect(reverse("waiter/tabs"))


class Waiter(WaiterLoginRequiredMixin, views.View):
    def get(self, request):
        return redirect(reverse("waiter/tabs"))

    class Tabs(WaiterLoginRequiredMixin, views.View):
        def get(self, request):
            context = Context(request, "waiter/tabs/index.html")
            tabs = []
            tabs_list = Tab.objects.filter(state=Tab.OPEN)
            for tab in tabs_list:
                tabs.append(prepare_tab_dict(tab))

            context['tabs'] = tabs
            context['products'] = []
            for product in Product.objects.all():
                context['products'].append({
                    'id': product.id,
                    'name': product.name,
                })

            if request.user.is_manager:
                context['paid_tabs'] = Tab.objects.filter(state=Tab.PAID)
            return context.render()

        def post(self, request):
            if "newTabName" in request.POST:
                try:
                    tab = Tab()
                    tab.name = request.POST["newTabName"]
                    tab.owner = request.user
                    tab.clean()
                    tab.save()
                except ValueError as err:
                    messages.warning(request, f"Creating Tab failed: {err.message}")
            return self.get(request)

        class Tab(WaiterLoginRequiredMixin, views.View):
            def fill_data(self, request, id, update_handler=None):
                context = Context(request, "waiter/tabs/tab.html")
                context["id"] = id
                try:
                    tab = Tab.objects.get(id=id)
                    context["tab_open"] = tab.state == Tab.OPEN
                    context["tab_my"] = tab.owner == request.user

                    if update_handler:
                        update_handler(context, tab)

                    tab.refresh_from_db()
                    context["tab_open"] = tab.state == Tab.OPEN
                    context["tab_my"] = tab.owner == request.user
                    context["transfer_request_exists"] = tab.transfer_request_exists
                    context["waiters"] = User.objects.filter(is_waiter=True)
                    if tab.owner:
                        context["waiters"] = context["waiters"].exclude(username=tab.owner.username)

                    current_till = request.user.current_till
                    if current_till:
                        context["money_counts"] = [method for method in current_till.tillmoneycount_set.all()
                                                   if method.paymentMethod.enabled]
                        context["change_method_name"] = current_till.changeMethod.name

                    context["tab"] = prepare_tab_dict(tab)
                    context["payments"] = tab.payments.all()
                except Tab.DoesNotExist:
                    messages.error(request, "Invalid request: specified Tab does not exist. "
                                            "Go back to previous page and try it again.")
                return context

            def get(self, request, id):
                context = self.fill_data(request, id)
                return context.render()

            def post(self, request, id):
                def update_handler(context, tab):
                    if context["tab_open"]:
                        if check_dict(request.POST, ["moneyCountId", "amount"]) and tab:
                            if context["tab_my"]:
                                try:
                                    money_count_id = uuid.UUID(request.POST["moneyCountId"])
                                    context["last_used_method"] = money_count_id
                                    amount = decimal.Decimal(request.POST["amount"])
                                    if amount < 0:
                                        messages.warning(request, "Payment amount must be greater than zero.")
                                    else:
                                        money_count = request.user.current_till.tillmoneycount_set.get(
                                            id=money_count_id)
                                        payment = PaymentInTab()
                                        payment.tab = tab
                                        payment.method = money_count
                                        payment.amount = amount
                                        payment.clean()
                                        payment.save()
                                        messages.success(request, "Payment created successfully")
                                except TillMoneyCount.DoesNotExist:
                                    messages.warning(request, "Invalid request: Payment method does not exist")
                                except ValidationError as err:
                                    messages.warning(request, f"Creating the payment failed: {err.message}")
                            else:
                                messages.warning(request, f"Only the tab owner can create payments")
                        if check_dict(request.POST, ["paymentId", "delete"]) and tab:
                            try:
                                payment_id = uuid.UUID(request.POST["paymentId"])
                                payment = PaymentInTab.objects.get(id=payment_id, tab=tab)
                                payment.delete()
                                messages.success(request, "Payment was deleted successfully")
                            except PaymentInTab.DoesNotExist:
                                messages.warning(request,
                                                 "The specified payment can't be deleted as it does not exist.")
                        if check_dict(request.POST, ["close"]) and tab:
                            try:
                                change_payment = tab.mark_paid(request.user)
                                messages.success(request, "The Tab was marked as paid.")
                                if change_payment:
                                    messages.info(request, f"The remaining variance of {change_payment.amount} was "
                                                           f"returned via {change_payment.method.paymentMethod.name}")
                            except ValidationError as err:
                                messages.warning(request, f"Closing this Tab failed: {err.message}")
                    else:
                        messages.error(request, "This Tab is closed and cannot be edited")

                context = self.fill_data(request, id, update_handler)
                return context.render()

            class RequestTransfer(WaiterLoginRequiredMixin, views.View):
                def post(self, request, id):
                    if "newOwnerUsername" in request.POST:
                        try:
                            tab = Tab.objects.get(id=id)
                            if tab.owner == request.user:
                                new_owner = User.objects.get(username=request.POST["newOwnerUsername"])
                                transfer_request = TabTransferRequest()
                                transfer_request.tab = tab
                                transfer_request.requester = request.user
                                transfer_request.new_owner = new_owner
                                transfer_request.clean()
                                transfer_request.save()
                                channel_layer = get_channel_layer()
                                async_to_sync(channel_layer.group_send)(
                                    "notifications_manager",
                                    {
                                        "type": "notification.tab_transfer_request",
                                        "tab_transfer_request": {
                                            "notification_type": "tab_transfer_request",
                                            "request_id": str(transfer_request.id),
                                            "tab_name": transfer_request.tab.name,
                                            "requester_name": transfer_request.requester.name,
                                            "new_owner_name": transfer_request.new_owner.name,
                                            "transfer_mode": "transfer",
                                        },
                                    },
                                )
                                messages.success(request, f"A transfer to user {new_owner.name} was requested.")
                            else:
                                messages.warning(request, f"Only the tab owner can request transfers to another user.")
                        except Tab.DoesNotExist:
                            messages.error(request, "That tab does not exist.")
                        except User.DoesNotExist:
                            messages.error(request, "The requested new user does not exist.")
                        except ValidationError as err:
                            messages.error(request, f"Request creation failed: {err.message}")
                    else:
                        messages.warning(request, "newOwnerUsername parameter was missing. Please try it again.")
                    return redirect(reverse("waiter/tabs/tab", kwargs={"id": id}))

            class RequestClaim(WaiterLoginRequiredMixin, views.View):
                def get(self, request, id):
                    try:
                        tab = Tab.objects.get(id=id)
                        if tab.owner != request.user:
                            transfer_request = TabTransferRequest()
                            transfer_request.tab = tab
                            transfer_request.requester = request.user
                            transfer_request.new_owner = request.user
                            transfer_request.clean()
                            transfer_request.save()
                            channel_layer = get_channel_layer()
                            async_to_sync(channel_layer.group_send)(
                                "notifications_manager",
                                {
                                    "type": "notification.tab_transfer_request",
                                    "tab_transfer_request": {
                                        "notification_type": "tab_transfer_request",
                                        "request_id": str(transfer_request.id),
                                        "tab_name": transfer_request.tab.name,
                                        "requester_name": transfer_request.requester.name,
                                        "new_owner_name": transfer_request.new_owner.name,
                                        "transfer_mode": "claim",
                                    },
                                },
                            )
                            messages.success(request, f"A claim was requested.")
                        else:
                            messages.warning(request, f"The tab owner can't request claims on his own tabs.")
                    except Tab.DoesNotExist:
                        messages.error(request, "That tab does not exist.")
                    except User.DoesNotExist:
                        messages.error(request, "The requested new user does not exist.")
                    except ValidationError as err:
                        messages.error(request, f"Request creation failed: {err.message}")
                    return redirect(reverse("waiter/tabs/tab", kwargs={"id": id}))

            class ChangeOwner(ManagerLoginRequiredMixin, views.View):
                def post(self, request, id):
                    if "newOwnerUsername" in request.POST:
                        try:
                            tab = Tab.objects.get(id=id)
                            new_owner = User.objects.get(username=request.POST["newOwnerUsername"])
                            tab.owner = new_owner
                            tab.clean()
                            tab.save()
                            messages.success(request, f"Owner was changed.")
                        except Tab.DoesNotExist:
                            messages.error(request, "That tab does not exist.")
                        except User.DoesNotExist:
                            messages.error(request, "The requested new owbner does not exist.")
                        except ValidationError as err:
                            messages.error(request, f"Owner change failed: {err.message}")
                    else:
                        messages.warning(request, "newOwnerUsername parameter was missing. Please try it again.")
                    return redirect(reverse("waiter/tabs/tab", kwargs={"id": id}))

    class Orders(WaiterLoginRequiredMixin, views.View):
        def get(self, request):
            context = Context(request, "waiter/orders/index.html")
            context["waiting"] = ProductInTab.objects.filter(state=ProductInTab.ORDERED).order_by("orderedAt")
            context["preparing"] = ProductInTab.objects.filter(state=ProductInTab.PREPARING).order_by("preparingAt")
            context["prepared"] = ProductInTab.objects.filter(state=ProductInTab.TO_SERVE).order_by("preparedAt")
            context["served"] = ProductInTab.objects.filter(state=ProductInTab.SERVED).order_by("orderedAt")
            return context.render()

        class Order(WaiterLoginRequiredMixin, views.View):
            def get(self, request, id):
                messages.info(request, "Well that was disappointing...")
                return redirect(reverse("waiter/orders"))

            class Bump(WaiterLoginRequiredMixin, views.View):
                def get(self, request, id, count):
                    try:
                        product = ProductInTab.objects.get(id=id)
                        for i in range(count):
                            if not product.bump():
                                messages.warning(request, "You attempted to bump the order beyond its capabilities, "
                                                          "it can only take so much.")
                                break
                    except ProductInTab.DoesNotExist:
                        messages.error(request, "The Product order can't be found and thus wasn't bumped.")
                    except ValidationError as err:
                        messages.error(request, f"An error occurred while bumping the product: {err.message}")
                    return redirect(reverse("waiter/orders"))

            class RequestVoid(WaiterLoginRequiredMixin, views.View):
                def get(self, request, id, format=None):
                    try:
                        order = ProductInTab.objects.get(id=id)
                        void_request = OrderVoidRequest(order=order, waiter=request.user)
                        void_request.clean()
                        void_request.save()
                        channel_layer = get_channel_layer()
                        async_to_sync(channel_layer.group_send)(
                            "notifications_manager",
                            {
                                "type": "notification.void_request",
                                "void_request": {
                                    "notification_type": "void_request",
                                    "request_id": str(void_request.id),
                                    "user": {
                                        "first_name": void_request.waiter.first_name,
                                        "last_name": void_request.waiter.last_name,
                                        "username": void_request.waiter.username,
                                    },
                                    "order": {
                                        "id": str(void_request.order.id),
                                        "product_name": void_request.order.product.name,
                                        "state": void_request.order.state,
                                        "ordered_at": str(void_request.order.orderedAt),
                                        "preparing_at": str(void_request.order.preparingAt),
                                        "prepared_at": str(void_request.order.preparedAt),
                                        "served_at": str(void_request.order.servedAt),
                                        "note": void_request.order.note,
                                        "tab_name": void_request.order.tab.name,
                                    }
                                }
                            },
                        )
                        messages.success(request, f"Void of a {order.product.name} requested")
                    except ValidationError as err:
                        messages.error(request, err.message)
                    except ProductInTab.DoesNotExist:
                        messages.error(request, "The Product order can't be found and thus void wasn't requested.")
                    return redirect(request.GET["next"] if "next" in request.GET else reverse("waiter/orders"))

            class Void(ManagerLoginRequiredMixin, views.View):
                def get(self, request, id):
                    try:
                        order = ProductInTab.objects.get(id=id)
                        order.void()
                        messages.success(request, f"Order of a {order.product.name} voided")
                    except ProductInTab.DoesNotExist:
                        messages.error(request, "The Product order can't be found and thus wasn't voided.")
                    except ValidationError as err:
                        messages.error(request, f"Failed voiding order of {order.product.name}: {err.message}")
                    return redirect(request.GET["next"] if "next" in request.GET else reverse("waiter/orders"))

            class AuthenticateAndVoid(WaiterLoginRequiredMixin, views.View):
                def get(self, request, id):
                    context = Context(request, "waiter/orders/order/authenticateAndVoid.html")
                    try:
                        context["id"] = id
                        context["order"] = ProductInTab.objects.get(id=id)
                        context["form"] = AuthenticationForm()
                        if "next" in request.GET:
                            context["next"] = request.GET["next"]
                        return context.render()
                    except ProductInTab.DoesNotExist:
                        messages.error(request, "The Product order can't be found and thus wasn't voided.")
                    return redirect(request.GET["next"] if "next" in request.GET else reverse("waiter/orders"))

                def post(self, request, id):
                    if check_dict(request.POST, ["username", "password"]):
                        try:
                            order = ProductInTab.objects.get(id=id)
                            form = AuthenticationForm(data=request.POST)
                            if form.is_valid() and (user := form.authenticate()):
                                if user.is_manager:
                                    order.void()
                                    messages.success(request, f"Order of a {order.product.name} voided")
                                else:
                                    messages.warning(request, "Only managers can directly void items. "
                                                              "Please enter credentials of a manager.")
                            else:
                                messages.warning(request, "Wrong username/password")
                        except ProductInTab.DoesNotExist:
                            messages.error(request, "The Product order can't be found and thus wasn't voided.")
                        except ValidationError as err:
                            messages.error(request, f"Failed voiding order of {order.product.name}: {err.message}")
                    else:
                        messages.error(request, "Username or password was missing in the request")

                    return redirect(request.GET["next"] if "next" in request.GET else reverse("waiter/orders"))


class Manager(ManagerLoginRequiredMixin, views.View):
    def get(self, request):
        return redirect(reverse("manager/users"))

    class Users(ManagerLoginRequiredMixin, views.View):
        def get(self, request):
            context = Context(request, "manager/users/index.html")
            search = request.GET.get("search", "")

            users = User.objects.filter(
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search)) \
                .order_by("last_name", "first_name")
            context['me'] = request.user.username
            context['search'] = search
            context.add_pagination_context(users, 'users')

            return context.render()

        class User(ManagerLoginRequiredMixin, views.View):
            def get(self, request, username):
                context = Context(request, "manager/users/user.html")
                try:
                    user = User.objects.get(username=username)
                    context["user"] = user
                    if username == request.user.username:
                        context["password_change_blocked"] = 1
                    elif not request.user.can_change_password(user):
                        context["password_change_blocked"] = 2
                    else:
                        context["password_change_blocked"] = 0
                except User.DoesNotExist:
                    context["user"] = False
                return context.render()

            def post(self, request, username):
                context = Context(request, "manager/users/user.html")
                try:
                    user = User.objects.get(username=username)
                    if username == request.user.username:
                        context["password_change_blocked"] = 1
                    elif not request.user.can_change_password(user):
                        context["password_change_blocked"] = 2
                    else:
                        context["password_change_blocked"] = 0
                    if "new_password" in request.POST:
                        if username == request.user.username:
                            messages.error(request, 'You can\'t change your own password. To do so, '
                                                    f'please follow <a href="{reverse("password_change")}"> '
                                                    'this link</a>.')
                        elif request.user.can_change_password(user):
                            new_password = request.POST["new_password"]
                            try:
                                validate_password(new_password)
                                user.set_password(new_password)
                                user.clean()
                                user.save()
                                messages.success(request, "Password changed")
                            except ValidationError as err:
                                message = "Password change failed: <ul>"
                                for emsg in err.messages:
                                    message += f"<li>{emsg}</li>"
                                message += "</ul>"
                                messages.warning(request, message)
                        else:
                            messages.warning(request, "You can't change password of this user")
                    context["user"] = user
                except User.DoesNotExist:
                    context["user"] = False
                return context.render()

        class Create(ManagerLoginRequiredMixin, views.View):
            def get(self, request):
                context = Context(request, "manager/users/create.html")
                context["form"] = CreateUserForm()
                return context.render()

            def post(self, request):
                user = User()
                form = CreateUserForm(request.POST, instance=user)
                if form.is_valid():
                    if request.user.is_director:
                        form.save()
                    else:
                        form.save(commit=False)
                        if user.is_manager or user.is_director:
                            messages.warning(request, "As a manager, you can only grant other users the waiter role. "
                                                      "Other roles were removed.")
                            user.is_manager = False
                            user.is_director = False
                        user.save()
                    messages.success(request, f"The user {form.cleaned_data['username']} was created successfully")
                    return redirect(reverse("manager/users"))

                context = Context(request, "manager/users/create.html")
                context["form"] = form
                return context.render()

    class Tills(ManagerLoginRequiredMixin, views.View):
        def get(self, request):
            context = Context(request, "manager/tills/index.html")
            search = request.GET.get("search", "")
            deposit_filter = request.GET.get("deposit_filter", "")

            open_tills = Till.objects.filter(state=Till.OPEN).filter(
                Q(cashiers__first_name__icontains=search) |
                Q(cashiers__last_name__icontains=search) |
                Q(cashiers__username__icontains=search)
            )
            stopped_tills = Till.objects.filter(state=Till.STOPPED).filter(
                Q(cashiers__first_name__icontains=search) |
                Q(cashiers__last_name__icontains=search) |
                Q(cashiers__username__icontains=search)
            )
            counted_tills = Till.objects.filter(state=Till.COUNTED).filter(
                Q(cashiers__first_name__icontains=search) |
                Q(cashiers__last_name__icontains=search) |
                Q(cashiers__username__icontains=search)
            )

            deposits = set()
            deposits.update(open_tills.values_list('deposit',flat=True))
            deposits.update(stopped_tills.values_list('deposit',flat=True))
            deposits.update(counted_tills.values_list('deposit',flat=True))
            context["deposits"] = deposits
            context["deposit_filter"] = deposit_filter

            if deposit_filter:
                open_tills = open_tills.filter(deposit__exact=deposit_filter)
                stopped_tills = stopped_tills.filter(deposit__exact=deposit_filter)
                counted_tills = counted_tills.filter(deposit__exact=deposit_filter)
            context.add_pagination_context(open_tills, 'open', page_get_name="page_open",
                                           page_length_get_name="page_length_open")
            context.add_pagination_context(stopped_tills, 'stopped', page_get_name="page_stopped",
                                           page_length_get_name="page_length_stopped")
            context.add_pagination_context(counted_tills, 'counted', page_get_name="page_counted",
                                           page_length_get_name="page_length_counted")
            context["search"] = search

            return context.render()

        class Assign(ManagerLoginRequiredMixin, views.View):
            def get(self, request):
                context = Context(request, "manager/tills/assign.html")

                context["users"] = User.objects.filter(is_waiter=True, current_till=None)
                context["options"] = Deposit.objects.filter(enabled=True)

                return context.render()

            def post(self, request):
                context = Context(request, "manager/tills/assign.html")
                if check_dict(request.POST, ["users", "options"]):
                    usernames = request.POST.getlist("users")
                    options_id = request.POST["options"]

                    try:
                        options = Deposit.objects.get(id=uuid.UUID(options_id))
                        till = options.create_till()
                        for username in usernames:
                            user = User.objects.get(username=username)
                            if user.current_till:
                                messages.warning(request,
                                                 f"The user {user} was excluded from this Till "
                                                 f"as they already have another Till assigned.")
                            else:
                                try:
                                    user.current_till = till
                                    user.clean()
                                    user.save()
                                    till.cashiers.add(user)
                                except ValidationError as err:
                                    messages.warning(request, f"The user {user} was not added to this Till: "
                                                              f"{err.message}")
                        messages.success(request, "The till was assigned successfully")
                    except User.DoesNotExist:
                        messages.error(request, "One of the selected users does not exist")
                    except Deposit.DoesNotExist:
                        messages.error(request,
                                       "The selected payment options config does not exist. It may have also been "
                                       "disabled by a director.")
                    except ValidationError as err:
                        messages.error(request, f"Failed creating the Till: {err.message}")
                else:
                    messages.error(request, "Some required fields are missing")

                context["users"] = User.objects.filter(is_waiter=True, current_till=None)
                context["options"] = Deposit.objects.filter(enabled=True)

                return context.render()

        class Till(ManagerLoginRequiredMixin, views.View):
            def get(self, request, id):
                context = Context(request, "manager/tills/till/index.html")
                try:
                    till = Till.objects.filter(state=Till.COUNTED).get(id=id)
                    context["id"] = id
                    counts = till.tillmoneycount_set.all()
                    context["counts"] = []
                    context["edits"] = []
                    context["totals"] = {"expected": 0, "counted": 0, "variance": 0}

                    for count in counts:
                        expected = count.expected
                        counted = count.counted
                        variance = counted - expected
                        context["counts"].append({
                            "methodName": count.paymentMethod.name,
                            "expected": expected,
                            "counted": counted,
                            "variance": variance,
                            "varianceUp": variance > 0,
                            "varianceDown": variance < 0,
                        })
                        context["totals"]["expected"] += expected
                        context["totals"]["counted"] += counted
                        context["totals"]["variance"] += variance

                        for edit in count.tilledit_set.order_by('created').all():
                            context["edits"].append(edit)

                    context["totals"]["varianceDown"] = context["totals"]["variance"] < 0
                    context["totals"]["varianceUp"] = context["totals"]["variance"] > 0

                    context["till"] = {
                        "cashiers": [],
                        "deposit": till.deposit,
                        "openedAt": till.openedAt,
                        "stoppedAt": till.stoppedAt,
                        "countedAt": till.countedAt,
                        "countedBy": till.countedBy,
                    }
                    for cashier in till.cashiers.all():
                        context["till"]["cashiers"].append(cashier.name)

                    context["show_value"] = True
                except Till.DoesNotExist:
                    pass
                return context.render()

            class Stop(ManagerLoginRequiredMixin, views.View):
                def get(self, request, id):
                    try:
                        till = Till.objects.get(id=id)
                        if till.stop():
                            messages.success(request,
                                             'The till was stopped successfully. It is now available for counting.')
                        else:
                            messages.warning(request,
                                             f'The till is in a state from which it cannot be closed: {till.state}')
                    except Till.DoesNotExist:
                        messages.error(request, 'The specified till does not exist.')
                    except ValidationError as err:
                        messages.error(request, f"Failed stopping Till: {err.message}")
                    return redirect(reverse("manager/tills"))

            class Count(ManagerLoginRequiredMixin, views.View):
                def get(self, request, id, zeroed=None):
                    context = Context(request, "manager/tills/till/count.html")
                    context["id"] = id
                    zeroed = zeroed or []

                    try:
                        till = Till.objects.get(id=id)

                        counts = till.tillmoneycount_set.all()
                        context["counts"] = []
                        context["totals"] = {
                            "counted": 0,
                            "expected": 0,
                            "variance": 0,
                        }
                        for count in counts:
                            expected = count.expected
                            variance = count.amount - expected
                            if variance > 0:
                                warn = "The counted amount is higher than expected"
                            elif variance < 0:
                                warn = "The counted amount is lower than expected"
                            else:
                                warn = None

                            context["counts"].append({
                                "id": count.id,
                                "name": count.paymentMethod.name,
                                "amount": count.amount,
                                "expected": expected,
                                "variance": variance,
                                "warn": warn,
                                "zeroed": count.id in zeroed,
                            })
                            context["totals"]["counted"] += count.amount
                            context["totals"]["expected"] += expected
                            context["totals"]["variance"] += variance
                        if context["totals"]["variance"] > 0:
                            context["totals"]["warn"] = "The total is higher than expected"
                        if context["totals"]["variance"] < 0:
                            context["totals"]["danger"] = "Some money is (still) missing!"
                    except Till.DoesNotExist:
                        messages.error(request, "The specified till does not exist")
                    except KeyError:
                        messages.error(request,
                                       "One of the counts required was missing in the request. Please fill all counts")

                    return context.render()

                def post(self, request, id):
                    till = Till.objects.get(id=id)
                    zeroed = []

                    counts = till.tillmoneycount_set.all()
                    for count in counts:
                        count.amount = float(request.POST[f"counted-{count.id}"])
                        if count.amount < 0:
                            zeroed.append(count.id)
                            count.amount = 0
                        try:
                            count.clean()
                            count.save()
                        except ValidationError as err:
                            messages.warning(request, f"Count {count.paymentMethod.name} was not saved due to error: "
                                                      f"{err.message}")

                    return self.get(request, id, zeroed)

            class Close(ManagerLoginRequiredMixin, views.View):
                def get(self, request, id):
                    try:
                        till = Till.objects.get(id=id)
                        if till.close(request):
                            messages.success(request, "The till was closed successfully")
                        else:
                            messages.warning(request,
                                             f'The till is in a state from which it cannot be closed: {till.state}')
                    except Till.DoesNotExist:
                        messages.error(request, 'The specified till does not exist.')
                    except ValidationError as err:
                        messages.error(request, f"Failed closing Till: {err.message}")
                    return redirect(reverse("manager/tills"))

            class Edit(ManagerLoginRequiredMixin, views.View):
                def get(self, request, id):
                    context = Context(request, "manager/tills/till/edit.html")
                    try:
                        till = Till.objects.filter(state=Till.COUNTED).get(id=id)
                        context["id"] = id
                        context["counts"] = till.tillmoneycount_set.all()
                    except Till.DoesNotExist:
                        messages.error(request,
                                       'The selected till is not available for edits. It either does not exist or '
                                       'is in a state that does not allow edits.')

                    return context.render()

                def post(self, request, id):
                    context = Context(request, "manager/tills/till/edit.html")
                    try:
                        till = Till.objects.filter(state=Till.COUNTED).get(id=id)
                        if "save" in request.POST:
                            try:
                                count_id = request.POST["count"]
                                amount = float(request.POST["amount"])
                                reason = request.POST["reason"]
                                count = till.tillmoneycount_set.get(id=count_id)
                                edit = count.add_edit(amount, reason)
                                if not edit:
                                    messages.warning(request, 'Zero edits can\'t be saved.')
                                elif edit.amount > amount:
                                    messages.info(request,
                                                  f"The edit had to be changed so that total amount of money "
                                                  f"wouldn't be negative. Actual saved amount is {edit.amount} "
                                                  f"and new counted amount is {count.counted}.")
                                else:
                                    messages.success(request, 'The edit was saved.')
                            except TillMoneyCount.DoesNotExist:
                                messages.warning(request,
                                                 'The specified payment method does not exist in this till. Please try again.'
                                                 )
                            except ValidationError as err:
                                messages.error(request, f"Creating Till edit failed: {err.message}")
                        context["id"] = id
                        context["counts"] = till.tillmoneycount_set.all()
                    except Till.DoesNotExist:
                        messages.error(request,
                                       'The selected till is not available for edits. It either does not exist or '
                                       'is in a state that does not allow edits.')

                    return context.render()

    class Requests(ManagerLoginRequiredMixin, views.View):
        def get(self, request):
            context = Context(request, "manager/requests/index.html")
            context["void_requests_open"] = OrderVoidRequest.objects.filter(resolution__isnull=True)
            context["transfer_requests_open"] = TabTransferRequest.objects.all()
            return context.render()

        class Void(ManagerLoginRequiredMixin, views.View):
            def get(self, request):
                context = Context(request, "manager/requests/void.html")
                context["void_requests_open"] = OrderVoidRequest.objects.filter(resolution__isnull=True)
                context.add_pagination_context(OrderVoidRequest.objects.exclude(resolution__isnull=True),
                                               "closed_requests")
                return context.render()

            class Resolve(ManagerLoginRequiredMixin, views.View):
                def get(self, request, id, resolution):
                    if resolution not in ["approve", "reject"]:
                        messages.error(request, f"The specified resolution '{resolution}' is not valid. "
                                                "It must be either approve or reject.")
                    else:
                        try:
                            void_request = OrderVoidRequest.objects.get(id=id)
                            if resolution == "approve" and void_request.approve(request.user):
                                messages.success(request, f"The request from {void_request.waiter.name} "
                                                          f"to void {void_request.order.product.name} was approved.")
                            elif resolution == "reject" and void_request.reject(request.user):
                                messages.success(request, f"The request from {void_request.waiter.name} "
                                                          f"to void {void_request.order.product.name} was rejected.")
                            else:
                                messages.warning(request, f"The request from {void_request.waiter.name} "
                                                          f"to void {void_request.order.product.name} was already "
                                                          f"{void_request.get_resolution_display().lower()} earlier.")
                        except OrderVoidRequest.DoesNotExist:
                            messages.error(request, "The specified Void request does not exist.")
                        except ValidationError as err:
                            messages.error(request, f"Resolving void request failed: {err.message}")

                    return redirect(reverse("manager/requests/void"))

        class Transfer(ManagerLoginRequiredMixin, views.View):
            def get(self, request):
                return redirect(reverse("manager/requests"))

            class Resolve(ManagerLoginRequiredMixin, views.View):
                def get(self, request, id, resolution):
                    if resolution not in ["approve", "reject"]:
                        messages.error(request, f"The specified resolution '{resolution}' is not valid. "
                                                "It must be either approve or reject.")
                    else:
                        try:
                            transfer_request = TabTransferRequest.objects.get(id=id)
                            if resolution == "approve":
                                transfer_request.approve(request.user)
                                messages.success(request, f"The request from {transfer_request.requester.name} "
                                                          f"to transfer tab {transfer_request.tab.name} to "
                                                          f"{transfer_request.new_owner.name} was approved.")
                            elif resolution == "reject":
                                transfer_request.reject(request.user)
                                messages.success(request, f"The request from {transfer_request.requester.name} "
                                                          f"to transfer tab {transfer_request.tab.name} to "
                                                          f"{transfer_request.new_owner.name} was rejected.")
                        except TabTransferRequest.DoesNotExist:
                            messages.error(request, "The specified Transfer request does not exist.")
                        except ValidationError as err:
                            messages.error(request, f"Resolving transfer request failed: {err.message}")

                    return redirect(reverse("manager/requests/transfer"))


class Director(DirectorLoginRequiredMixin, views.View):
    def get(self, request):
        return redirect(reverse("director/finance"))

    class Finance(DirectorLoginRequiredMixin, views.View):
        def get(self, request):
            return redirect(reverse("director/finance"))

        class Currencies(DirectorLoginRequiredMixin, views.View):
            def get(self, request):
                context = Context(request, "director/finance/currencies.html")
                search = request.GET.get('search', '')
                activity_filter = request.GET.get('activity_filter', '')

                currencies = Currency.objects.filter(
                    Q(name__icontains=search) | Q(code__icontains=search) | Q(symbol__icontains=search)).order_by(
                    'code')
                if activity_filter:
                    if activity_filter == "enabled":
                        currencies = currencies.filter(enabled=True)
                    if activity_filter == "disabled":
                        currencies = currencies.filter(enabled=False)
                context.add_pagination_context(currencies, 'currencies')

                context["search"] = search
                context["activity_filter"] = activity_filter

                return context.render()

        class Methods(DirectorLoginRequiredMixin, views.View):
            def get(self, request, form=None, show_modal=False):
                context = Context(request, "director/finance/methods.html")

                form = form or CreatePaymentMethodForm()
                context['form'] = form
                search = request.GET.get('search', '')
                currency_filter = int(request.GET['currency']) if 'currency' in request.GET else None
                context["currency_filter"] = currency_filter

                methods = PaymentMethod.objects.filter(
                    Q(name__icontains=search) | Q(currency__name__icontains=search))
                if currency_filter:
                    methods = methods.filter(currency__pk=currency_filter)

                context.add_pagination_context(methods, 'methods')

                context["search"] = search
                context["currencies"] = Currency.objects.all().order_by("name")

                context["showModal"] = show_modal
                return context.render()

            def post(self, request):
                method = PaymentMethod()
                form = CreatePaymentMethodForm(request.POST, instance=method)
                if form.is_valid():
                    form.save()
                    messages.success(request, "Method created successfully")
                    form = CreatePaymentMethodForm()
                    show_modal = False
                else:
                    show_modal = True
                return self.get(request, form, show_modal)

            class Method(DirectorLoginRequiredMixin, views.View):
                def get(self, request, id):
                    messages.info(request, f"Well that was disappointing...")
                    return redirect(reverse("director/finance/methods"))

                class Delete(DirectorLoginRequiredMixin, views.View):
                    def get(self, request, id):
                        try:
                            method = PaymentMethod.objects.get(id=id)
                            method.delete()
                            messages.success(request, "The payment method was successfully deleted")
                        except PaymentMethod.DoesNotExist:
                            messages.warning(request, "The specified Payment method doesn't exist")
                        except ProtectedError:
                            messages.error(request, "The specified method can't be deleted as other records such as "
                                                    "payments or tills depend on it. You can remove it from the deposits "
                                                    "to prevent further use.")
                        return redirect(reverse("director/finance/methods"))

        class Deposits(DirectorLoginRequiredMixin, views.View):

            def get(self, request):
                context = Context(request, 'director/finance/deposits/index.html')
                search = request.GET.get('search', '')
                activity_filter = request.GET.get('activity_filter', '')
                deposits = Deposit.objects.filter(name__icontains=search)
                if activity_filter == 'enabled':
                    deposits = deposits.filter(enabled=True)
                elif activity_filter == 'disabled':
                    deposits = deposits.filter(enabled=False)
                context.add_pagination_context(deposits, 'deposits')
                context['search'] = search
                context['activity_filter'] = activity_filter
                return context.render()

            def post(self, request):
                if 'deleteDepositId' in request.POST:
                    id = uuid.UUID(request.POST['deleteDepositId'])
                    try:
                        deposit = Deposit.objects.get(id=id)
                        deposit.delete()
                        messages.success(request, f'Deposit {deposit.name} deleted successfully')
                    except Deposit.DoesNotExist:
                        messages.error(request, 'Deleting deposit failed, deposit does not exist')
                return self.get(request)

            class Edit(DirectorLoginRequiredMixin, views.View):
                def get(self, request, id=None):
                    context = Context(request, 'director/finance/deposits/edit.html')
                    context['id'] = id
                    if id:
                        context['is_edit'] = True
                        try:
                            deposit = Deposit.objects.get(id=id)
                            context['form'] = CreateEditDepositForm(instance=deposit)

                        except Deposit.DoesNotExist:
                            messages.warning(request, "This deposit does not exist")
                            return redirect(reverse('director/finance/deposits'))
                    else:
                        context['form'] = CreateEditDepositForm()
                    return context.render()

                def post(self, request, id=None):
                    context = Context(request, 'director/finance/deposits/edit.html')
                    context['id'] = id
                    if id:
                        context['is_edit'] = True
                        try:
                            deposit = Deposit.objects.get(id=id)
                        except Deposit.DoesNotExist:
                            messages.error(request, "This deposit does not exist, so it could not be saved")
                            return redirect(reverse('director/finance/deposits'))
                    else:
                        deposit = Deposit()

                    form = CreateEditDepositForm(request.POST, instance=deposit)
                    if form.is_valid():
                        form.save()
                        messages.success(request, "Deposit saved successfully!")
                        return redirect(reverse('director/finance/deposits'))
                    else:
                        context['form'] = form
                        return context.render()

    class Units(DirectorLoginRequiredMixin, views.View):
        def get(self, request):
            context = Context(request, 'director/units/index.html')
            context['groups'] = UnitGroup.objects.all()

            return context.render()

        def post(self, request):
            context = Context(request, 'director/units/index.html')
            if check_dict(request.POST, ['newUnitGroupName', 'newUnitGroupSymbol']):
                group = UnitGroup()
                group.name = request.POST['newUnitGroupName']
                group.symbol = request.POST['newUnitGroupSymbol']
                try:
                    group.clean()
                    group.save()
                    messages.success(request, "The unit group was created successfully")
                except ValidationError as err:
                    messages.warning(request, f"An error occurred during saving of the group: {err.message}")
            if check_dict(request.POST, ['groupId', 'newUnitName', 'newUnitSymbol', 'newUnitRatio']):
                group_id = uuid.UUID(request.POST['groupId'])
                try:
                    unit = Unit()
                    unit.name = request.POST['newUnitName']
                    unit.symbol = request.POST['newUnitSymbol']
                    unit.ratio = float(request.POST['newUnitRatio'])
                    unit.group = UnitGroup.objects.get(id=group_id)
                    try:
                        unit.clean()
                        unit.save()
                        messages.success(request, "The unit was created successfully")
                    except ValidationError as err:
                        messages.warning(request, f"An error occurred during saving of the unit: {err.message}")
                except UnitGroup.DoesNotExist:
                    messages.error(request, "Creation failed: Unit Group does not exist!")

            if 'deleteUnitId' in request.POST:
                try:
                    unit = Unit.objects.get(id=uuid.UUID(request.POST['deleteUnitId']))
                    unit.delete()
                    messages.success(request, "The unit was deleted successfully")
                except Unit.DoesNotExist:
                    messages.error(request, "Deletion failed: Unit does not exist!")
            if 'deleteUnitGroupId' in request.POST:
                try:
                    group = UnitGroup.objects.get(id=uuid.UUID(request.POST['deleteUnitGroupId']))
                    group.delete()
                    messages.success(request, "The unit group was deleted successfully")
                except UnitGroup.DoesNotExist:
                    messages.error(request, "Deletion failed: Unit Group does not exist!")
                except ProtectedError:
                    messages.warning(request, "Deletion failed: an Item depends on this Unit Group!")
            context['groups'] = UnitGroup.objects.all()

            return context.render()

    class Menu(DirectorLoginRequiredMixin, views.View):
        def get(self, request):
            return redirect(reverse("director/menu/products"))

        class Products(DirectorLoginRequiredMixin, views.View):
            def fill_data(self, request):
                context = Context(request, 'director/menu/products/index.html')
                search = request.GET.get('search', '')
                activity_filter = request.GET.get('activity_filter', '')

                products = Product.objects.filter(name__icontains=search).order_by('name')
                if activity_filter:
                    if activity_filter == "enabled":
                        products = products.filter(enabled=True)
                    if activity_filter == "disanbled":
                        products = products.filter(enabled=False)
                context.add_pagination_context(products, 'products')

                context["search"] = search
                context["activity_filter"] = activity_filter

                return context

            def get(self, request, *args, **kwargs):
                context = self.fill_data(request)
                context["create_product_form"] = CreateEditProductForm()

                return context.render()

            def post(self, request, *args, **kwargs):
                product = Product()
                form = CreateEditProductForm(request.POST, instance=product)
                if form.is_valid():
                    form.save()
                    messages.success(request, "Product created successfully")
                    return redirect("director/menu/products/product", id=product.id)
                else:
                    context = self.fill_data(request)
                    context["create_product_form"] = form

                    return context.render()

            class Product(DirectorLoginRequiredMixin, views.View):
                def get(self, request, id, *args, **kwargs):
                    context = Context(request, 'director/menu/products/product.html')
                    context["id"] = id
                    try:
                        product = Product.objects.get(id=id)
                        form = CreateEditProductForm(instance=product)
                        items_formset = ItemsInProductFormSet(queryset=ItemInProduct.objects.filter(product=product))
                        context["form"] = form
                        context["items_formset"] = items_formset
                        context["show_form"] = True
                    except Product.DoesNotExist:
                        context["show_does_not_exist"] = True
                    return context.render()

                def post(self, request, id, *args, **kwargs):
                    context = Context(request, 'director/menu/products/product.html')
                    context["id"] = id
                    try:
                        product = Product.objects.get(id=id)
                        if "formSelector" in request.POST:
                            product_changed = request.POST["formSelector"] == "product"
                            product_form = CreateEditProductForm(request.POST if product_changed else None,
                                                                 instance=product)
                            if product_changed and product_form.is_valid():
                                product_form.save()
                                messages.success(request, "Product successfully updated")
                                product_form = CreateEditProductForm(instance=product)

                            items_changed = request.POST["formSelector"] == "items"
                            items_formset = ItemsInProductFormSet(
                                request.POST if items_changed else None,
                                queryset=ItemInProduct.objects.filter(
                                    product=product
                                )
                            )
                            if items_changed and items_formset.is_valid():
                                items_formset.save(commit=False)
                                for form in items_formset.forms:
                                    form.instance.product = product
                                items_formset.save()
                                items_formset = ItemsInProductFormSet(
                                    queryset=ItemInProduct.objects.filter(
                                        product=product
                                    )
                                )

                            context["form"] = product_form
                            context["items_formset"] = items_formset
                            context["show_form"] = True
                        else:
                            messages.error(request, "Something went wrong, please retry your last action")
                    except Product.DoesNotExist:
                        context["show_does_not_exist"] = True
                    return context.render()

                class Delete(DirectorLoginRequiredMixin, views.View):
                    def get(self, request, id, *args, **kwargs):
                        try:
                            product = Product.objects.get(id=id)
                            product.delete()
                            messages.success(request, f"Product {product.name} was deleted.")
                            return redirect(reverse("director/menu/products"))
                        except Product.DoesNotExist:
                            return redirect(reverse("director/menu/products/product", id=id))
                        except ProtectedError:
                            messages.error(request, "This Product can't be deleted as it was already ordered")
                            return redirect(reverse("director/menu/products/product", id=id))

        class Items(views.View):
            def fill_data(self, request):
                context = Context(request, 'director/menu/items/index.html')
                search = request.GET.get('search', '')
                unit_group_id = uuid.UUID(request.GET['unit_group']) \
                    if "unit_group" in request.GET and request.GET["unit_group"] else None
                items = Item.objects.filter(name__icontains=search)
                if unit_group_id:
                    try:
                        unit_group = UnitGroup.objects.get(id=unit_group_id)
                        items = items.filter(unitGroup=unit_group)
                    except UnitGroup.DoesNotExist:
                        messages.warning(request, "The Unit group you attempted to filter by does not exist, ignoring.")
                context.add_pagination_context(items, "items")
                context["search"] = search
                context["unit_groups"] = UnitGroup.objects.all()
                context["unit_group"] = unit_group_id
                return context

            def get(self, request):
                context = self.fill_data(request)
                context["create_item_form"] = CreateItemForm()
                return context.render()

            def post(self, request):
                item = Item()
                create_item_form = CreateItemForm(request.POST, instance=item)
                if create_item_form.is_valid():
                    create_item_form.save()
                    create_item_form = CreateItemForm()

                context = self.fill_data(request)
                context["create_item_form"] = create_item_form
                return context.render()

            class Item(views.View):
                def get(self, request, id):
                    messages.info(request, "That link leads nowhere, you better be safe.")
                    return redirect(reverse("director/menu/items"))

                class Delete(views.View):
                    def get(self, request, id):
                        try:
                            item = Item.objects.get(id=id)
                            item.delete()
                            messages.success(request, f"The item {item.name} was successfully deleted")
                        except Item.DoesNotExist:
                            messages.error(request, "The item wasn't deleted as it can't be found.")
                        except ProtectedError:
                            messages.error(request, "The item can't be deleted because it is used by a Product")
                        return redirect(reverse('director/menu/items'))


class Debug:
    class CreateUser(views.View):
        def get(self, request, form=None):
            if settings.DEBUG:
                form = form or CreateUserForm(initial={
                    "username": "test",
                    "first_name": "Test",
                    "last_name": "Test",
                    "email": "test@puda.pos.beer",
                    "mobile_phone": "603123456",
                    "password1": "pudapos123",
                    "password2": "pudapos123",
                    "is_waiter": True,
                })
                return render(request, template_name="debug/create_user.html",
                              context={"form": form or CreateUserForm()})
            else:
                return HttpResponseForbidden()

        def post(self, request):
            if settings.DEBUG:
                form = CreateUserForm(request.POST)
                if form.is_valid():
                    form.save()
                    messages.success(request, "User created")
                    form = None
                return self.get(request, form)
            else:
                return HttpResponseForbidden()
