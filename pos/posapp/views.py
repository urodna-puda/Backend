import decimal
import random
import string
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
        self.request = request
        self.template_name = template_name
        self.page = self.request.get_full_path()[1:]
        self.waiter_role = self.request.user.is_waiter
        self.manager_role = self.request.user.is_manager
        self.director_role = self.request.user.is_director
        self.notifications = Notifications()
        self.version = settings.VERSION
        self.data = {}

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


def base_method(method):
    method.is_base = True
    return method


class BaseView(views.View):
    def dispatch(self, request, *args, **kwargs):
        if self.request.method.lower() == "options":
            return self.options(request, *args, **kwargs)
        elif self.request.method.lower() in self.http_method_names:
            handler = getattr(self, request.method.lower(), self.http_method_not_allowed)
        else:
            handler = self.http_method_not_allowed
        return handler(*args, **kwargs)

    def _allowed_methods(self):
        return [m.upper() for m in self.http_method_names if not hasattr(getattr(self, m), 'is_base')]

    @base_method
    def get(self, *args, **kwargs):
        pass

    @base_method
    def post(self, *args, **kwargs):
        pass

    @base_method
    def put(self, *args, **kwargs):
        pass

    @base_method
    def patch(self, *args, **kwargs):
        pass

    @base_method
    def delete(self, *args, **kwargs):
        pass

    @base_method
    def head(self, *args, **kwargs):
        pass

    @base_method
    def trace(self, *args, **kwargs):
        pass


class TabBaseView(WaiterLoginRequiredMixin, BaseView):
    template_name = ""
    next_url = ""

    def fill_data(self, tab, update=False):
        context = Context(self.request, self.template_name)
        context["id"] = tab.id
        context["tab_open"] = tab.state == Tab.OPEN
        context["tab_my"] = tab.owner == self.request.user
        context["next_url"] = self.next_url

        if update:
            self.update_handler(context, tab)

        tab.refresh_from_db()
        context["tab_open"] = tab.state == Tab.OPEN
        context["tab_my"] = tab.owner == self.request.user
        context["transfer_request_exists"] = tab.transfer_request_exists
        context["waiters"] = User.objects.filter(is_waiter=True)
        if tab.owner:
            context["waiters"] = context["waiters"].exclude(username=tab.owner.username)

        current_till = self.request.user.current_till
        if current_till:
            context["money_counts"] = [method for method in current_till.tillmoneycount_set.all()
                                       if method.paymentMethod.enabled]
            context["change_method_name"] = current_till.changeMethod.name

        context["tab"] = prepare_tab_dict(tab)
        context["payments"] = tab.payments.all()

        return context

    def update_handler(self, context, tab):
        if context["tab_open"]:
            if check_dict(self.request.POST, ["moneyCountId", "amount"]) and tab:
                if context["tab_my"]:
                    try:
                        money_count_id = uuid.UUID(self.request.POST["moneyCountId"])
                        context["last_used_method"] = money_count_id
                        amount = decimal.Decimal(self.request.POST["amount"])
                        if amount < 0:
                            messages.warning(self.request, "Payment amount must be greater than zero.")
                        else:
                            money_count = self.request.user.current_till.tillmoneycount_set.get(
                                id=money_count_id)
                            payment = PaymentInTab()
                            payment.tab = tab
                            payment.method = money_count
                            payment.amount = amount
                            payment.clean()
                            payment.save()
                            messages.success(self.request, "Payment created successfully")
                    except TillMoneyCount.DoesNotExist:
                        messages.warning(self.request, "Invalid request: Payment method does not exist")
                    except ValidationError as err:
                        messages.warning(self.request, f"Creating the payment failed: {err.message}")
                else:
                    messages.warning(self.request, f"Only the tab owner can create payments")
            if check_dict(self.request.POST, ["paymentId", "delete"]) and tab:
                try:
                    payment_id = uuid.UUID(self.request.POST["paymentId"])
                    payment = PaymentInTab.objects.get(id=payment_id, tab=tab)
                    payment.delete()
                    messages.success(self.request, "Payment was deleted successfully")
                except PaymentInTab.DoesNotExist:
                    messages.warning(self.request,
                                     "The specified payment can't be deleted as it does not exist.")
            if check_dict(self.request.POST, ["close"]) and tab:
                try:
                    change_payment = tab.mark_paid(self.request.user)
                    messages.success(self.request, "The Tab was marked as paid.")
                    if change_payment:
                        messages.info(self.request, f"The remaining variance of {change_payment.amount} was "
                                                    f"returned via {change_payment.method.paymentMethod.name}")
                except ValidationError as err:
                    messages.warning(self.request, f"Closing this Tab failed: {err.message}")
        else:
            messages.error(self.request, "This Tab is closed and cannot be edited")


class DisambiguationView(BaseView):
    name = ""
    links = []
    breadcrumbs = []
    """
    template: ("", "", []),
    """

    def get(self, *args, **kwargs):
        context = Context(self.request, "disambiguation.html")
        context["name"] = self.name
        context["links"] = DisambiguationView.generate_ul(self.links)
        context["breadcrumbs"] = self.breadcrumbs
        return context.render()

    @staticmethod
    def generate_ul(links):
        if links:
            ul = "<ul>"
            for name, link, sub in links:
                ul += f'<li><a href="{reverse(link)}">{name}</a>{DisambiguationView.generate_ul(sub)}</li>'
            ul += "</ul>"
        else:
            ul = ""
        return ul


@login_required
def index(request):
    if request.user.is_waiter:
        return redirect(reverse("waiter/tabs"))
    elif request.user.is_manager:
        return redirect(reverse("manager/tills"))
    elif request.user.is_director:
        return redirect(reverse("director/menu/products"))


class Waiter(WaiterLoginRequiredMixin, DisambiguationView):
    name = "Waiter"
    links = [
        ("Tabs", "waiter/tabs", []),
        ("Orders", "waiter/orders", []),
        ("Direct order", "waiter/direct", [
            ("New", "waiter/direct/new", []),
            ("Order", "waiter/direct/order", []),
            ("Checkout", "waiter/direct/pay", []),
        ]),
    ]
    breadcrumbs = [
        ("Home", "index"),
        ("Waiter",),
    ]

    class Tabs(WaiterLoginRequiredMixin, BaseView):
        def get(self, *args, **kwargs):
            context = Context(self.request, "waiter/tabs/index.html")
            tabs = []
            tabs_list = Tab.objects.filter(state=Tab.OPEN, temp_tab_owner__isnull=True)
            for tab in tabs_list:
                tabs.append(prepare_tab_dict(tab))

            context['tabs'] = tabs
            context['products'] = Product.objects.filter(enabled=True)

            if self.request.user.is_manager:
                context['paid_tabs'] = Tab.objects.filter(state=Tab.PAID)
            return context.render()

        def post(self, *args, **kwargs):
            if "newTabName" in self.request.POST:
                try:
                    tab = Tab()
                    tab.name = self.request.POST["newTabName"]
                    tab.owner = self.request.user
                    tab.clean()
                    tab.save()
                except ValueError as err:
                    messages.warning(self.request, f"Creating Tab failed: {err.message}")
            return self.get()

        class Tab(TabBaseView):
            template_name = "waiter/tabs/tab.html"

            def get(self, id, *args, **kwargs):
                self.next_url = reverse("waiter/tabs/tab", kwargs={"id": id})
                try:
                    tab = Tab.objects.filter(temp_tab_owner__isnull=True).get(id=id)
                    context = self.fill_data(tab)
                    return context.render()
                except Tab.DoesNotExist:
                    messages.error(self.request, "Invalid request: specified Tab does not exist. "
                                                 "Go back to previous page and try it again.")
                    return redirect(reverse("waiter/tabs"))

            def post(self, id, *args, **kwargs):
                self.next_url = reverse("waiter/tabs/tab", kwargs={"id": id})
                try:
                    tab = Tab.objects.filter(temp_tab_owner__isnull=True).get(id=id)
                    context = self.fill_data(tab, True)
                    return context.render()
                except Tab.DoesNotExist:
                    messages.error(self.request, "Invalid request: specified Tab does not exist. "
                                                 "Go back to previous page and try it again.")
                    return redirect(reverse("waiter/tabs"))

            class RequestTransfer(WaiterLoginRequiredMixin, BaseView):
                def post(self, id, *args, **kwargs):
                    if "newOwnerUsername" in self.request.POST:
                        try:
                            tab = Tab.objects.filter(temp_tab_owner__isnull=True).get(id=id)
                            if tab.owner == self.request.user:
                                new_owner = User.objects.get(username=self.request.POST["newOwnerUsername"])
                                transfer_request = TabTransferRequest()
                                transfer_request.tab = tab
                                transfer_request.requester = self.request.user
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
                                messages.success(self.request, f"A transfer to user {new_owner.name} was requested.")
                            else:
                                messages.warning(self.request,
                                                 f"Only the tab owner can request transfers to another user.")
                        except Tab.DoesNotExist:
                            messages.error(self.request, "That tab does not exist.")
                        except User.DoesNotExist:
                            messages.error(self.request, "The requested new user does not exist.")
                        except ValidationError as err:
                            messages.error(self.request, f"Request creation failed: {err.message}")
                    else:
                        messages.warning(self.request, "newOwnerUsername parameter was missing. Please try it again.")
                    return redirect(reverse("waiter/tabs/tab", kwargs={"id": id}))

            class RequestClaim(WaiterLoginRequiredMixin, BaseView):
                def get(self, id, *args, **kwargs):
                    try:
                        tab = Tab.objects.filter(temp_tab_owner__isnull=True).get(id=id)
                        if tab.owner != self.request.user:
                            transfer_request = TabTransferRequest()
                            transfer_request.tab = tab
                            transfer_request.requester = self.request.user
                            transfer_request.new_owner = self.request.user
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
                            messages.success(self.request, f"A claim was requested.")
                        else:
                            messages.warning(self.request, f"The tab owner can't request claims on his own tabs.")
                    except Tab.DoesNotExist:
                        messages.error(self.request, "That tab does not exist.")
                    except User.DoesNotExist:
                        messages.error(self.request, "The requested new user does not exist.")
                    except ValidationError as err:
                        messages.error(self.request, f"Request creation failed: {err.message}")
                    return redirect(reverse("waiter/tabs/tab", kwargs={"id": id}))

            class ChangeOwner(ManagerLoginRequiredMixin, BaseView):
                def post(self, id, *args, **kwargs):
                    if "newOwnerUsername" in self.request.POST:
                        try:
                            tab = Tab.objects.filter(temp_tab_owner__isnull=True).get(id=id)
                            new_owner = User.objects.get(username=self.request.POST["newOwnerUsername"])
                            tab.owner = new_owner
                            tab.clean()
                            tab.save()
                            messages.success(self.request, f"Owner was changed.")
                        except Tab.DoesNotExist:
                            messages.error(self.request, "That tab does not exist.")
                        except User.DoesNotExist:
                            messages.error(self.request, "The requested new owbner does not exist.")
                        except ValidationError as err:
                            messages.error(self.request, f"Owner change failed: {err.message}")
                    else:
                        messages.warning(self.request, "newOwnerUsername parameter was missing. Please try it again.")
                    return redirect(reverse("waiter/tabs/tab", kwargs={"id": id}))

    class Orders(WaiterLoginRequiredMixin, BaseView):
        def get(self, *args, **kwargs):
            context = Context(self.request, "waiter/orders/index.html")
            context["waiting"] = ProductInTab.objects.filter(state=ProductInTab.ORDERED).order_by("orderedAt")
            context["preparing"] = ProductInTab.objects.filter(state=ProductInTab.PREPARING).order_by("preparingAt")
            context["prepared"] = ProductInTab.objects.filter(state=ProductInTab.TO_SERVE).order_by("preparedAt")
            context["served"] = ProductInTab.objects.filter(state=ProductInTab.SERVED).order_by("orderedAt")
            return context.render()

        class Order(WaiterLoginRequiredMixin, BaseView):
            def get(self, id, *args, **kwargs):
                messages.info(self.request, "Well that was disappointing...")
                return redirect(reverse("waiter/orders"))

            class Bump(WaiterLoginRequiredMixin, BaseView):
                def get(self, id, count, *args, **kwargs):
                    try:
                        product = ProductInTab.objects.get(id=id)
                        for i in range(count):
                            if not product.bump():
                                messages.warning(self.request,
                                                 "You attempted to bump the order beyond its capabilities, "
                                                 "it can only take so much.")
                                break
                    except ProductInTab.DoesNotExist:
                        messages.error(self.request, "The Product order can't be found and thus wasn't bumped.")
                    except ValidationError as err:
                        messages.error(self.request, f"An error occurred while bumping the product: {err.message}")
                    return redirect(reverse("waiter/orders"))

            class RequestVoid(WaiterLoginRequiredMixin, BaseView):
                def get(self, id, *args, **kwargs):
                    try:
                        order = ProductInTab.objects.get(id=id)
                        void_request = OrderVoidRequest(order=order, waiter=self.request.user)
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
                        messages.success(self.request, f"Void of a {order.product.name} requested")
                    except ValidationError as err:
                        messages.error(self.request, err.message)
                    except ProductInTab.DoesNotExist:
                        messages.error(self.request, "The Product order can't be found and thus void wasn't requested.")
                    return redirect(
                        self.request.GET["next"] if "next" in self.request.GET else reverse("waiter/orders"))

            class Void(ManagerLoginRequiredMixin, BaseView):
                def get(self, id, *args, **kwargs):
                    try:
                        order = ProductInTab.objects.get(id=id)
                        order.void()
                        messages.success(self.request, f"Order of a {order.product.name} voided")
                    except ProductInTab.DoesNotExist:
                        messages.error(self.request, "The Product order can't be found and thus wasn't voided.")
                    except ValidationError as err:
                        messages.error(self.request, f"Failed voiding order of {order.product.name}: {err.message}")
                    return redirect(
                        self.request.GET["next"] if "next" in self.request.GET else reverse("waiter/orders"))

            class AuthenticateAndVoid(WaiterLoginRequiredMixin, BaseView):
                def get(self, id, *args, **kwargs):
                    context = Context(self.request, "waiter/orders/order/authenticateAndVoid.html")
                    try:
                        context["id"] = id
                        context["order"] = ProductInTab.objects.get(id=id)
                        context["form"] = AuthenticationForm()
                        if "next" in self.request.GET:
                            context["next"] = self.request.GET["next"]
                        return context.render()
                    except ProductInTab.DoesNotExist:
                        messages.error(self.request, "The Product order can't be found and thus wasn't voided.")
                    return redirect(
                        self.request.GET["next"] if "next" in self.request.GET else reverse("waiter/orders"))

                def post(self, id, *args, **kwargs):
                    if check_dict(self.request.POST, ["username", "password"]):
                        try:
                            order = ProductInTab.objects.get(id=id)
                            form = AuthenticationForm(data=self.request.POST)
                            if form.is_valid() and (user := form.authenticate()):
                                if user.is_manager:
                                    order.void()
                                    messages.success(self.request, f"Order of a {order.product.name} voided")
                                else:
                                    messages.warning(self.request, "Only managers can directly void items. "
                                                                   "Please enter credentials of a manager.")
                            else:
                                messages.warning(self.request, "Wrong username/password")
                        except ProductInTab.DoesNotExist:
                            messages.error(self.request, "The Product order can't be found and thus wasn't voided.")
                        except ValidationError as err:
                            messages.error(self.request, f"Failed voiding order of {order.product.name}: {err.message}")
                    else:
                        messages.error(self.request, "Username or password was missing in the self.request")

                    return redirect(
                        self.request.GET["next"] if "next" in self.request.GET else reverse("waiter/orders"))

    class Direct(WaiterLoginRequiredMixin, BaseView):
        def get(self, *args, **kwargs):
            if self.request.user.current_temp_tab:
                return redirect(reverse("waiter/direct/order"))
            else:
                return redirect(reverse("waiter/direct/new"))

        class New(WaiterLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "waiter/direct/new.html")
                if self.request.user.current_temp_tab:
                    messages.warning(self.request, "You already have an open order. No need to start a new one.")
                    return redirect(reverse("waiter/direct"))
                return context.render()

            def post(self, *args, **kwargs):
                if self.request.user.current_temp_tab:
                    messages.warning(self.request, "You already have an open order. No need to start a new one.")
                    return redirect(reverse("waiter/direct"))
                tab = Tab()
                slug = ''.join(
                    random.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/") for _ in
                    range(11))
                tab.name = f"@DIRECT {slug}"
                tab.owner = self.request.user
                try:
                    tab.clean()
                    tab.save()
                    self.request.user.current_temp_tab = tab
                    self.request.user.clean()
                    self.request.user.save()
                except ValidationError as err:
                    messages.error(self.request, "Something went wrong when starting order: " + err.message)
                return redirect(reverse("waiter/direct"))

        class Order(WaiterLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "waiter/direct/order.html")
                if not self.request.user.current_temp_tab:
                    messages.warning(self.request, "You don't have an open order. Start one now.")
                    return redirect(reverse("waiter/direct"))
                context["tab"] = prepare_tab_dict(self.request.user.current_temp_tab)
                context["tab_open"] = True
                context["next_url"] = reverse("waiter/direct/order")
                context["replace_finish_button"] = True
                context["products"] = Product.objects.filter(enabled=True)
                context["payments"] = self.request.user.current_temp_tab.payments.all()
                context["hide_delete_payment"] = True
                return context.render()

        class Pay(TabBaseView):
            template_name = "waiter/direct/pay.html"

            def get(self, *args, **kwargs):
                if not self.request.user.current_temp_tab:
                    messages.warning(self.request, "You don't have an open order. Start one now.")
                    return redirect(reverse("waiter/direct"))
                self.next_url = reverse("waiter/direct/order")
                context = self.fill_data(self.request.user.current_temp_tab)
                context["show_back_button"] = True
                return context.render()

            def post(self, *args, **kwargs):
                if not self.request.user.current_temp_tab:
                    messages.warning(self.request, "You don't have an open order. Start one now.")
                    return redirect(reverse("waiter/direct"))
                self.next_url = reverse("waiter/direct/order")
                context = self.fill_data(self.request.user.current_temp_tab, True)
                context["show_back_button"] = True
                return context.render()


class Manager(ManagerLoginRequiredMixin, DisambiguationView):
    name = "Manager"
    links = [
        ("Users", "manager/users", [
            ("Create", "manager/users/create", []),
        ]),
        ("Tills", "manager/tills", [
            ("Assign", "manager/tills/assign", []),
        ]),
        ("Requests", "manager/requests", [
            ("Void requests", "manager/requests/void", []),
        ]),
    ]
    breadcrumbs = [
        ("Home", "index"),
        ("Manager",),
    ]

    class Users(ManagerLoginRequiredMixin, BaseView):
        def get(self, *args, **kwargs):
            context = Context(self.request, "manager/users/index.html")
            search = self.request.GET.get("search", "")

            users = User.objects.filter(
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search)) \
                .order_by("last_name", "first_name")
            context['me'] = self.request.user.username
            context['search'] = search
            context.add_pagination_context(users, 'users')

            return context.render()

        class User(ManagerLoginRequiredMixin, BaseView):
            def get(self, username, *args, **kwargs):
                context = Context(self.request, "manager/users/user.html")
                try:
                    user = User.objects.get(username=username)
                    context["user"] = user
                    if username == self.request.user.username:
                        context["password_change_blocked"] = 1
                    elif not self.request.user.can_change_password(user):
                        context["password_change_blocked"] = 2
                    else:
                        context["password_change_blocked"] = 0
                except User.DoesNotExist:
                    context["user"] = False
                return context.render()

            def post(self, username, *args, **kwargs):
                context = Context(self.request, "manager/users/user.html")
                try:
                    user = User.objects.get(username=username)
                    if username == self.request.user.username:
                        context["password_change_blocked"] = 1
                    elif not self.request.user.can_change_password(user):
                        context["password_change_blocked"] = 2
                    else:
                        context["password_change_blocked"] = 0
                    if "new_password" in self.request.POST:
                        if username == self.request.user.username:
                            messages.error(self.request, 'You can\'t change your own password. To do so, '
                                                         f'please follow <a href="{reverse("password_change")}"> '
                                                         'this link</a>.')
                        elif self.request.user.can_change_password(user):
                            new_password = self.request.POST["new_password"]
                            try:
                                validate_password(new_password)
                                user.set_password(new_password)
                                user.clean()
                                user.save()
                                messages.success(self.request, "Password changed")
                            except ValidationError as err:
                                message = "Password change failed: <ul>"
                                for emsg in err.messages:
                                    message += f"<li>{emsg}</li>"
                                message += "</ul>"
                                messages.warning(self.request, message)
                        else:
                            messages.warning(self.request, "You can't change password of this user")
                    context["user"] = user
                except User.DoesNotExist:
                    context["user"] = False
                return context.render()

        class Create(ManagerLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "manager/users/create.html")
                context["form"] = CreateUserForm()
                return context.render()

            def post(self, *args, **kwargs):
                user = User()
                form = CreateUserForm(self.request.POST, instance=user)
                if form.is_valid():
                    if self.request.user.is_director:
                        form.save()
                    else:
                        form.save(commit=False)
                        if user.is_manager or user.is_director:
                            messages.warning(self.request,
                                             "As a manager, you can only grant other users the waiter role. "
                                             "Other roles were removed.")
                            user.is_manager = False
                            user.is_director = False
                        user.save()
                    messages.success(self.request, f"The user {form.cleaned_data['username']} was created successfully")
                    return redirect(reverse("manager/users"))

                context = Context(self.request, "manager/users/create.html")
                context["form"] = form
                return context.render()

    class Tills(ManagerLoginRequiredMixin, BaseView):
        def get(self, *args, **kwargs):
            context = Context(self.request, "manager/tills/index.html")
            search = self.request.GET.get("search", "")
            deposit_filter = self.request.GET.get("deposit_filter", "")

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
            deposits.update(open_tills.values_list('deposit', flat=True))
            deposits.update(stopped_tills.values_list('deposit', flat=True))
            deposits.update(counted_tills.values_list('deposit', flat=True))
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

        class Assign(ManagerLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "manager/tills/assign.html")

                context["users"] = User.objects.filter(is_waiter=True, current_till=None)
                context["options"] = Deposit.objects.filter(enabled=True)

                return context.render()

            def post(self, *args, **kwargs):
                context = Context(self.request, "manager/tills/assign.html")
                if check_dict(self.request.POST, ["users", "options"]):
                    usernames = self.request.POST.getlist("users")
                    options_id = self.request.POST["options"]

                    try:
                        options = Deposit.objects.get(id=uuid.UUID(options_id))
                        if options.enabled:
                            till = options.create_till()
                        else:
                            messages.error(self.request, 'Can not create Till from disabled Deposit')
                        for username in usernames:
                            user = User.objects.get(username=username)
                            if user.current_till:
                                messages.warning(self.request,
                                                 f"The user {user} was excluded from this Till "
                                                 f"as they already have another Till assigned.")
                            else:
                                try:
                                    user.current_till = till
                                    user.clean()
                                    user.save()
                                    till.cashiers.add(user)
                                except ValidationError as err:
                                    messages.warning(self.request, f"The user {user} was not added to this Till: "
                                                                   f"{err.message}")
                        messages.success(self.request, "The till was assigned successfully")
                    except User.DoesNotExist:
                        messages.error(self.request, "One of the selected users does not exist")
                    except Deposit.DoesNotExist:
                        messages.error(self.request,
                                       "The selected payment options config does not exist. It may have also been "
                                       "disabled by a director.")
                    except ValidationError as err:
                        messages.error(self.request, f"Failed creating the Till: {err.message}")
                else:
                    messages.error(self.request, "Some required fields are missing")

                context["users"] = User.objects.filter(is_waiter=True, current_till=None)
                context["options"] = Deposit.objects.filter(enabled=True)

                return context.render()

        class Till(ManagerLoginRequiredMixin, BaseView):
            def get(self, id, *args, **kwargs):
                context = Context(self.request, "manager/tills/till/index.html")
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

            class Stop(ManagerLoginRequiredMixin, BaseView):
                def get(self, id, *args, **kwargs):
                    try:
                        till = Till.objects.get(id=id)
                        if till.stop():
                            messages.success(self.request,
                                             'The till was stopped successfully. It is now available for counting.')
                        else:
                            messages.warning(self.request,
                                             f'The till is in a state from which it cannot be closed: {till.state}')
                    except Till.DoesNotExist:
                        messages.error(self.request, 'The specified till does not exist.')
                    except ValidationError as err:
                        messages.error(self.request, f"Failed stopping Till: {err.message}")
                    return redirect(reverse("manager/tills"))

            class Count(ManagerLoginRequiredMixin, BaseView):
                def get(self, id, zeroed=None, *args, **kwargs):
                    context = Context(self.request, "manager/tills/till/count.html")
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
                        messages.error(self.request, "The specified till does not exist")
                    except KeyError:
                        messages.error(self.request, "One of the counts required was missing in the self.request. "
                                                     "Please fill all counts.")

                    return context.render()

                def post(self, id, *args, **kwargs):
                    till = Till.objects.get(id=id)
                    zeroed = []

                    counts = till.tillmoneycount_set.all()
                    for count in counts:
                        count.amount = float(self.request.POST[f"counted-{count.id}"])
                        if count.amount < 0:
                            zeroed.append(count.id)
                            count.amount = 0
                        try:
                            count.clean()
                            count.save()
                        except ValidationError as err:
                            messages.warning(self.request,
                                             f"Count {count.paymentMethod.name} was not saved due to error: "
                                             f"{err.message}")

                    return self.get(id, zeroed)

            class Close(ManagerLoginRequiredMixin, BaseView):
                def get(self, id, *args, **kwargs):
                    try:
                        till = Till.objects.get(id=id)
                        if till.close(self.request):
                            messages.success(self.request, "The till was closed successfully")
                        else:
                            messages.warning(self.request,
                                             f'The till is in a state from which it cannot be closed: {till.state}')
                    except Till.DoesNotExist:
                        messages.error(self.request, 'The specified till does not exist.')
                    except ValidationError as err:
                        messages.error(self.request, f"Failed closing Till: {err.message}")
                    return redirect(reverse("manager/tills"))

            class Edit(ManagerLoginRequiredMixin, BaseView):
                def get(self, id, *args, **kwargs):
                    context = Context(self.request, "manager/tills/till/edit.html")
                    try:
                        till = Till.objects.filter(state=Till.COUNTED).get(id=id)
                        context["id"] = id
                        context["counts"] = till.tillmoneycount_set.all()
                    except Till.DoesNotExist:
                        messages.error(self.request,
                                       'The selected till is not available for edits. It either does not exist or '
                                       'is in a state that does not allow edits.')

                    return context.render()

                def post(self, id, *args, **kwargs):
                    context = Context(self.request, "manager/tills/till/edit.html")
                    try:
                        till = Till.objects.filter(state=Till.COUNTED).get(id=id)
                        if "save" in self.request.POST:
                            try:
                                count_id = self.request.POST["count"]
                                amount = float(self.request.POST["amount"])
                                reason = self.request.POST["reason"]
                                count = till.tillmoneycount_set.get(id=count_id)
                                edit = count.add_edit(amount, reason)
                                if not edit:
                                    messages.warning(self.request, 'Zero edits can\'t be saved.')
                                elif edit.amount > amount:
                                    messages.info(self.request,
                                                  f"The edit had to be changed so that total amount of money "
                                                  f"wouldn't be negative. Actual saved amount is {edit.amount} "
                                                  f"and new counted amount is {count.counted}.")
                                else:
                                    messages.success(self.request, 'The edit was saved.')
                            except TillMoneyCount.DoesNotExist:
                                messages.warning(self.request, 'The specified payment method does not exist in this '
                                                               'till. Please try again.')
                            except ValidationError as err:
                                messages.error(self.request, f"Creating Till edit failed: {err.message}")
                        context["id"] = id
                        context["counts"] = till.tillmoneycount_set.all()
                    except Till.DoesNotExist:
                        messages.error(self.request,
                                       'The selected till is not available for edits. It either does not exist or '
                                       'is in a state that does not allow edits.')

                    return context.render()

    class Requests(ManagerLoginRequiredMixin, BaseView):
        def get(self, *args, **kwargs):
            context = Context(self.request, "manager/requests/index.html")
            context["void_requests_open"] = OrderVoidRequest.objects.filter(resolution__isnull=True)
            context["transfer_requests_open"] = TabTransferRequest.objects.all()
            return context.render()

        class Void(ManagerLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "manager/requests/void.html")
                context["void_requests_open"] = OrderVoidRequest.objects.filter(resolution__isnull=True)
                context.add_pagination_context(OrderVoidRequest.objects.exclude(resolution__isnull=True),
                                               "closed_requests")
                return context.render()

            class Resolve(ManagerLoginRequiredMixin, BaseView):
                def get(self, id, resolution, *args, **kwargs):
                    if resolution not in ["approve", "reject"]:
                        messages.error(self.request, f"The specified resolution '{resolution}' is not valid. "
                                                     "It must be either approve or reject.")
                    else:
                        try:
                            void_request = OrderVoidRequest.objects.get(id=id)
                            if resolution == "approve" and void_request.approve(self.request.user):
                                messages.success(self.request, f"The request from {void_request.waiter.name} "
                                                               f"to void {void_request.order.product.name} "
                                                               "was approved.")
                            elif resolution == "reject" and void_request.reject(self.request.user):
                                messages.success(self.request, f"The request from {void_request.waiter.name} "
                                                               f"to void {void_request.order.product.name} "
                                                               "was rejected.")
                            else:
                                messages.warning(self.request, f"The request from {void_request.waiter.name} "
                                                               f"to void {void_request.order.product.name} was already "
                                                               f"{void_request.get_resolution_display().lower()} "
                                                               "earlier.")
                        except OrderVoidRequest.DoesNotExist:
                            messages.error(self.request, "The specified Void request does not exist.")
                        except ValidationError as err:
                            messages.error(self.request, f"Resolving void request failed: {err.message}")

                    return redirect(reverse("manager/requests/void"))

        class Transfer(ManagerLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                return redirect(reverse("manager/requests"))

            class Resolve(ManagerLoginRequiredMixin, BaseView):
                def get(self, id, resolution, *args, **kwargs):
                    if resolution not in ["approve", "reject"]:
                        messages.error(self.request, f"The specified resolution '{resolution}' is not valid. "
                                                     "It must be either approve or reject.")
                    else:
                        try:
                            transfer_request = TabTransferRequest.objects.get(id=id)
                            if resolution == "approve":
                                transfer_request.approve(self.request.user)
                                messages.success(self.request, f"The request from {transfer_request.requester.name} "
                                                               f"to transfer tab {transfer_request.tab.name} to "
                                                               f"{transfer_request.new_owner.name} was approved.")
                            elif resolution == "reject":
                                transfer_request.reject(self.request.user)
                                messages.success(self.request, f"The request from {transfer_request.requester.name} "
                                                               f"to transfer tab {transfer_request.tab.name} to "
                                                               f"{transfer_request.new_owner.name} was rejected.")
                        except TabTransferRequest.DoesNotExist:
                            messages.error(self.request, "The specified Transfer request does not exist.")
                        except ValidationError as err:
                            messages.error(self.request, f"Resolving transfer request failed: {err.message}")

                    return redirect(reverse("manager/requests/transfer"))


class Director(DirectorLoginRequiredMixin, DisambiguationView):
    name = "Director"
    links = [
        ("Finance", "director/finance", [
            ("Currencies", "director/finance/currencies", []),
            ("Payment methods", "director/finance/methods", []),
            ("Deposits", "director/finance/deposits", [
                ("Create deposit", "director/finance/deposits/create", []),
            ]),
        ]),
        ("Units", "director/units", []),
        ("Menu", "director/menu", [
            ("Products", "director/menu/products", []),
            ("Items", "director/menu/items", []),
        ]),
    ]
    breadcrumbs = [
        ("Home", "index"),
        ("Director", ),
    ]

    class Finance(DirectorLoginRequiredMixin, DisambiguationView):
        name = "Finance"
        links = [
            ("Currencies", "director/finance/currencies", []),
            ("Payment methods", "director/finance/methods", []),
            ("Deposits", "director/finance/deposits", [
                ("Create deposit", "director/finance/deposits/create", []),
            ]),
        ]
        breadcrumbs = [
            ("Home", "index"),
            ("Director", "director"),
            ("Finance", ),
        ]

        class Currencies(DirectorLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "director/finance/currencies.html")
                search = self.request.GET.get('search', '')
                activity_filter = self.request.GET.get('activity_filter', '')

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

        class Methods(DirectorLoginRequiredMixin, BaseView):
            def get(self, form=None, show_modal=False, *args, **kwargs):
                context = Context(self.request, "director/finance/methods.html")

                form = form or CreatePaymentMethodForm()
                context['form'] = form
                search = self.request.GET.get('search', '')
                currency_filter = int(self.request.GET['currency']) if 'currency' in self.request.GET else None
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

            def post(self, *args, **kwargs):
                method = PaymentMethod()
                form = CreatePaymentMethodForm(self.request.POST, instance=method)
                if form.is_valid():
                    form.save()
                    messages.success(self.request, "Method created successfully")
                    form = CreatePaymentMethodForm()
                    show_modal = False
                else:
                    show_modal = True
                return self.get(form, show_modal)

            class Method(DirectorLoginRequiredMixin, BaseView):
                def get(self, id, *args, **kwargs):
                    messages.info(self.request, f"Well that was disappointing...")
                    return redirect(reverse("director/finance/methods"))

                class Delete(DirectorLoginRequiredMixin, BaseView):
                    def get(self, id, *args, **kwargs):
                        try:
                            method = PaymentMethod.objects.get(id=id)
                            method.delete()
                            messages.success(self.request, "The payment method was successfully deleted")
                        except PaymentMethod.DoesNotExist:
                            messages.warning(self.request, "The specified Payment method doesn't exist")
                        except ProtectedError:
                            messages.error(self.request,
                                           "The specified method can't be deleted as other records such as "
                                           "payments or tills depend on it. You can remove it from the deposits "
                                           "to prevent further use.")
                        return redirect(reverse("director/finance/methods"))

        class Deposits(DirectorLoginRequiredMixin, BaseView):

            def get(self, *args, **kwargs):
                context = Context(self.request, 'director/finance/deposits/index.html')
                search = self.request.GET.get('search', '')
                activity_filter = self.request.GET.get('activity_filter', '')
                deposits = Deposit.objects.filter(name__icontains=search)
                if activity_filter == 'enabled':
                    deposits = deposits.filter(enabled=True)
                elif activity_filter == 'disabled':
                    deposits = deposits.filter(enabled=False)
                context.add_pagination_context(deposits, 'deposits')
                context['search'] = search
                context['activity_filter'] = activity_filter
                return context.render()

            def post(self, *args, **kwargs):
                if 'deleteDepositId' in self.request.POST:
                    id = uuid.UUID(self.request.POST['deleteDepositId'])
                    try:
                        deposit = Deposit.objects.get(id=id)
                        deposit.delete()
                        messages.success(self.request, f'Deposit {deposit.name} deleted successfully')
                    except Deposit.DoesNotExist:
                        messages.error(self.request, 'Deleting deposit failed, deposit does not exist')
                return self.get(self.request)

            class Edit(DirectorLoginRequiredMixin, BaseView):
                def get(self, id=None, *args, **kwargs):
                    context = Context(self.request, 'director/finance/deposits/edit.html')
                    context['id'] = id
                    if id:
                        context['is_edit'] = True
                        try:
                            deposit = Deposit.objects.get(id=id)
                            context['form'] = CreateEditDepositForm(instance=deposit)

                        except Deposit.DoesNotExist:
                            messages.warning(self.request, "This deposit does not exist")
                            return redirect(reverse('director/finance/deposits'))
                    else:
                        context['form'] = CreateEditDepositForm()
                    return context.render()

                def post(self, id=None, *args, **kwargs):
                    context = Context(self.request, 'director/finance/deposits/edit.html')
                    context['id'] = id
                    if id:
                        context['is_edit'] = True
                        try:
                            deposit = Deposit.objects.get(id=id)
                        except Deposit.DoesNotExist:
                            messages.error(self.request, "This deposit does not exist, so it could not be saved")
                            return redirect(reverse('director/finance/deposits'))
                    else:
                        deposit = Deposit()

                    form = CreateEditDepositForm(self.request.POST, instance=deposit)
                    if form.is_valid():
                        form.save()
                        messages.success(self.request, "Deposit saved successfully!")
                        return redirect(reverse('director/finance/deposits'))
                    else:
                        context['form'] = form
                        return context.render()

    class Units(DirectorLoginRequiredMixin, BaseView):
        def get(self, *args, **kwargs):
            context = Context(self.request, 'director/units/index.html')
            context['groups'] = UnitGroup.objects.all()

            return context.render()

        def post(self, *args, **kwargs):
            context = Context(self.request, 'director/units/index.html')
            if check_dict(self.request.POST, ['newUnitGroupName', 'newUnitGroupSymbol']):
                group = UnitGroup()
                group.name = self.request.POST['newUnitGroupName']
                group.symbol = self.request.POST['newUnitGroupSymbol']
                try:
                    group.clean()
                    group.save()
                    messages.success(self.request, "The unit group was created successfully")
                except ValidationError as err:
                    messages.warning(self.request, f"An error occurred during saving of the group: {err.message}")
            if check_dict(self.request.POST, ['groupId', 'newUnitName', 'newUnitSymbol', 'newUnitRatio']):
                group_id = uuid.UUID(self.request.POST['groupId'])
                try:
                    unit = Unit()
                    unit.name = self.request.POST['newUnitName']
                    unit.symbol = self.request.POST['newUnitSymbol']
                    unit.ratio = float(self.request.POST['newUnitRatio'])
                    unit.group = UnitGroup.objects.get(id=group_id)
                    try:
                        unit.clean()
                        unit.save()
                        messages.success(self.request, "The unit was created successfully")
                    except ValidationError as err:
                        messages.warning(self.request, f"An error occurred during saving of the unit: {err.message}")
                except UnitGroup.DoesNotExist:
                    messages.error(self.request, "Creation failed: Unit Group does not exist!")

            if 'deleteUnitId' in self.request.POST:
                try:
                    unit = Unit.objects.get(id=uuid.UUID(self.request.POST['deleteUnitId']))
                    unit.delete()
                    messages.success(self.request, "The unit was deleted successfully")
                except Unit.DoesNotExist:
                    messages.error(self.request, "Deletion failed: Unit does not exist!")
            if 'deleteUnitGroupId' in self.request.POST:
                try:
                    group = UnitGroup.objects.get(id=uuid.UUID(self.request.POST['deleteUnitGroupId']))
                    group.delete()
                    messages.success(self.request, "The unit group was deleted successfully")
                except UnitGroup.DoesNotExist:
                    messages.error(self.request, "Deletion failed: Unit Group does not exist!")
                except ProtectedError:
                    messages.warning(self.request, "Deletion failed: an Item depends on this Unit Group!")
            context['groups'] = UnitGroup.objects.all()

            return context.render()

    class Menu(DirectorLoginRequiredMixin, DisambiguationView):
        name = "Menu"
        links = [
            ("Products", "director/menu/products", []),
            ("Items", "director/menu/items", []),
        ]
        breadcrumbs = [
            ("Home", "index"),
            ("Director", "director"),
            ("Menu", ),
        ]

        class Products(DirectorLoginRequiredMixin, BaseView):
            def fill_data(self, request):
                context = Context(self.request, 'director/menu/products/index.html')
                search = self.request.GET.get('search', '')
                activity_filter = self.request.GET.get('activity_filter', '')

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

            def get(self, *args, **kwargs):
                context = self.fill_data(self.request)
                context["create_product_form"] = CreateEditProductForm()

                return context.render()

            def post(self, *args, **kwargs):
                product = Product()
                form = CreateEditProductForm(self.request.POST, instance=product)
                if form.is_valid():
                    form.save()
                    messages.success(self.request, "Product created successfully")
                    return redirect("director/menu/products/product", id=product.id)
                else:
                    context = self.fill_data(self.request)
                    context["create_product_form"] = form

                    return context.render()

            class Product(DirectorLoginRequiredMixin, BaseView):
                def get(self, id, *args, **kwargs):
                    context = Context(self.request, 'director/menu/products/product.html')
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

                def post(self, id, *args, **kwargs):
                    context = Context(self.request, 'director/menu/products/product.html')
                    context["id"] = id
                    try:
                        product = Product.objects.get(id=id)
                        if "formSelector" in self.request.POST:
                            product_changed = self.request.POST["formSelector"] == "product"
                            product_form = CreateEditProductForm(self.request.POST if product_changed else None,
                                                                 instance=product)
                            if product_changed and product_form.is_valid():
                                product_form.save()
                                messages.success(self.request, "Product successfully updated")
                                product_form = CreateEditProductForm(instance=product)

                            items_changed = self.request.POST["formSelector"] == "items"
                            items_formset = ItemsInProductFormSet(
                                self.request.POST if items_changed else None,
                                queryset=ItemInProduct.objects.filter(
                                    product=product
                                )
                            )
                            if items_changed and items_formset.is_valid():
                                items_formset.save(commit=False)
                                for form in items_formset.forms:
                                    form.instance.product = product
                                items_formset.save()
                                messages.success(self.request, "Product successfully updated")
                                items_formset = ItemsInProductFormSet(
                                    queryset=ItemInProduct.objects.filter(
                                        product=product
                                    )
                                )

                            context["form"] = product_form
                            context["items_formset"] = items_formset
                            context["show_form"] = True
                        else:
                            messages.error(self.request, "Something went wrong, please retry your last action")
                    except Product.DoesNotExist:
                        context["show_does_not_exist"] = True
                    return context.render()

                class Delete(DirectorLoginRequiredMixin, BaseView):
                    def get(self, id, *args, **kwargs):
                        try:
                            product = Product.objects.get(id=id)
                            product.delete()
                            messages.success(self.request, f"Product {product.name} was deleted.")
                            return redirect(reverse("director/menu/products"))
                        except Product.DoesNotExist:
                            return redirect(reverse("director/menu/products/product", kwargs={"id": id}))
                        except ProtectedError:
                            messages.error(self.request, "This Product can't be deleted as it was already ordered")
                            return redirect(reverse("director/menu/products/product", kwargs={"id": id}))

        class Items(BaseView):
            def fill_data(self, request):
                context = Context(self.request, 'director/menu/items/index.html')
                search = self.request.GET.get('search', '')
                unit_group_id = uuid.UUID(self.request.GET['unit_group']) \
                    if "unit_group" in self.request.GET and self.request.GET["unit_group"] else None
                items = Item.objects.filter(name__icontains=search)
                if unit_group_id:
                    try:
                        unit_group = UnitGroup.objects.get(id=unit_group_id)
                        items = items.filter(unitGroup=unit_group)
                    except UnitGroup.DoesNotExist:
                        messages.warning(self.request,
                                         "The Unit group you attempted to filter by does not exist, ignoring.")
                context.add_pagination_context(items, "items")
                context["search"] = search
                context["unit_groups"] = UnitGroup.objects.all()
                context["unit_group"] = unit_group_id
                return context

            def get(self, *args, **kwargs):
                context = self.fill_data(self.request)
                context["create_item_form"] = CreateItemForm()
                return context.render()

            def post(self, *args, **kwargs):
                item = Item()
                create_item_form = CreateItemForm(self.request.POST, instance=item)
                if create_item_form.is_valid():
                    create_item_form.save()
                    create_item_form = CreateItemForm()

                context = self.fill_data(self.request)
                context["create_item_form"] = create_item_form
                return context.render()

            class Item(BaseView):
                def get(self, id, *args, **kwargs):
                    messages.info(self.request, "That link leads nowhere, you better be safe.")
                    return redirect(reverse("director/menu/items"))

                class Delete(BaseView):
                    def get(self, id, *args, **kwargs):
                        try:
                            item = Item.objects.get(id=id)
                            item.delete()
                            messages.success(self.request, f"The item {item.name} was successfully deleted")
                        except Item.DoesNotExist:
                            messages.error(self.request, "The item wasn't deleted as it can't be found.")
                        except ProtectedError:
                            messages.error(self.request, "The item can't be deleted because it is used by a Product")
                        return redirect(reverse('director/menu/items'))


class Debug:
    class CreateUser(BaseView):
        def get(self, form=None, *args, **kwargs):
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
                return render(self.request, template_name="debug/create_user.html",
                              context={"form": form or CreateUserForm()})
            else:
                return HttpResponseForbidden()

        def post(self, *args, **kwargs):
            if settings.DEBUG:
                form = CreateUserForm(self.request.POST)
                if form.is_valid():
                    form.save()
                    messages.success(self.request, "User created")
                    form = None
                return self.get(form)
            else:
                return HttpResponseForbidden()
