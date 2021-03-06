import datetime
import decimal
import inspect
import io
import logging
import mimetypes
import os
import random
import string
import uuid
from typing import Type

import pytz
import stringcase
from PIL import Image, UnidentifiedImageError
# Create your views here.
from PyPDF2 import PdfFileReader
from PyPDF2.utils import PdfReadError
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django import views
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q, ProtectedError
from django.db.transaction import atomic
from django.http import HttpResponseForbidden, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django_fsm import has_transition_perm
from django_fsm_log.models import StateLog

from posapp.forms import CreateUserForm, CreatePaymentMethodForm, CreateEditProductForm, ItemsInProductFormSet, \
    CreateItemForm, AuthenticationForm, CreateEditDepositForm, CreateEditExpenseForm, CreateEditMemberForm
from posapp.models import Tab, ProductInTab, Product, User, Currency, Till, Deposit, TillMoneyCount, \
    PaymentInTab, PaymentMethod, UnitGroup, Unit, ItemInProduct, Item, OrderVoidRequest, TabTransferRequest, Expense, \
    Member
from posapp.security.role_decorators import WaiterLoginRequiredMixin, ManagerLoginRequiredMixin, \
    DirectorLoginRequiredMixin

logger = logging.getLogger(__name__)


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


class TimelineItem:
    def __init__(self, timestamp):
        self.timestamp = timestamp
        self.icon = '<i class="{classes} ion"></i>'
        self.icon_classes = ''
        self.header = ''
        self.body = ''
        self.footer = ''

    @property
    def final_icon(self):
        return self.icon.format(classes=self.icon_classes)


class Context:
    def __init__(self, request, template_name, title=""):
        self.request = request
        self.template_name = template_name
        self.title = title
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

    def add_timeline_context(self, items, key, time_label_classes='bg-danger', reverse=False):
        items = sorted(items, key=lambda item: item.timestamp, reverse=reverse)
        dates = []
        last_date = None
        for item in items:
            date = item.timestamp.date()
            if date != last_date:
                dates.append({"date": date, "items": []})
                last_date = date
            dates[-1]["items"].append(item)
        self[key] = {"dates": dates, "time_label_classes": time_label_classes}

    def render(self, content_type=None, status=None, using=None):
        return render(self.request, self.template_name, dict(self), content_type, status, using)

    def __getitem__(self, item):
        return self.data[item]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __len__(self):
        return 7 + len(self.data)

    def __contains__(self, item):
        return item in self.data

    def __iter__(self):
        yield 'page', self.page
        yield 'title', self.title
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
    _name = None  # The name displayed to user, defaults to Foo Bar for FooBar class
    _url = None  # A part of the URL passed to path(), defaults to foo_bar for FooBar class
    _url_name = None  # A part of the name passed to path(), defaults to foo_bar for FooBar class
    _own_url_name = None  # Override the name of this view with this name directly
    _advertise = True

    @staticmethod
    def _inner_classes_list(cls, only_advertised=False):
        return [cls_attribute for cls_attribute in cls.__dict__.values()
                if inspect.isclass(cls_attribute)
                and issubclass(cls_attribute, BaseView)
                and (cls_attribute._advertise or not only_advertised)]

    @classmethod
    def name(cls):
        return stringcase.titlecase(cls.__name__) if cls._name is None else cls._name

    @classmethod
    def url(cls):
        return stringcase.snakecase(cls.__name__) if cls._url is None else cls._url

    @classmethod
    def url_name(cls):
        return stringcase.snakecase(cls.__name__) if cls._url_name is None else cls._url_name

    @classmethod
    def own_url_name(cls, url_name_base):
        return cls._own_url_name or (url_name_base + cls.url_name())

    @classmethod
    def generate_urls(cls, url_base="", url_name_base="", urls=None):
        if not urls:
            urls = []

        urls.append((url_base + cls.url(), cls.as_view(), cls.own_url_name(url_name_base)))
        for subcls in BaseView._inner_classes_list(cls):
            suburl_slash = '/' if cls.url() else ''
            suburl_name_slash = '/' if cls.url_name() else ''

            suburl_base = f"{url_base}{cls.url()}{suburl_slash}"
            suburl_name_base = f"{url_name_base}{cls.url_name()}{suburl_name_slash}"

            subcls.generate_urls(
                url_base=suburl_base,
                url_name_base=suburl_name_base,
                urls=urls
            )
        return urls

    def dispatch(self, request, *args, **kwargs):
        if self.request.method.lower() == "options":
            return self.options(request, *args, **kwargs)
        elif self.request.method in self._allowed_methods():
            return getattr(self, request.method.lower())(*args, **kwargs)
        else:
            return self.http_method_not_allowed(request, *args, **kwargs)

    def _allowed_methods(self):
        return [m.upper() for m in self.http_method_names if not hasattr(getattr(self, m), 'is_base')]

    def http_method_not_allowed(self, request, *args, **kwargs):
        logger.warning(
            'Method Not Allowed (%s): %s', request.method, request.path,
            extra={'status_code': 405, 'request': request}
        )
        error_view = ErrorView(request, 405)
        error_view.context["method"] = request.method
        error_view.context["allowed_methods"] = self._allowed_methods()
        return error_view.render()

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


class ErrorView:
    context: Context
    error: int

    def __init__(self, request, error: int, *, title="", comment=""):
        self.context = Context(request, f"error/{error}.html", f"Error {error}")
        self.context["title"] = title
        self.context["comment"] = comment
        self.error = error

    def render(self):
        return self.context.render(status=self.error)


class TabBaseView(WaiterLoginRequiredMixin, BaseView):
    template_name = ""
    next_url = ""

    def fill_data(self, tab, update=False):
        context = Context(self.request, self.template_name, f"{tab}")
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
    def get(self, *args, **kwargs):
        title = f"{self.name()} disambiguation" if self.name else "Disambiguation"
        context = Context(self.request, "disambiguation.html", title)

        context["name"] = self.name or self.__class__.__name__.lower()
        context["links"] = DisambiguationView.generate_ul(self.__class__)
        context["breadcrumbs"] = DisambiguationView.generate_breadcrumbs(self.__class__, Index)

        return context.render()

    @staticmethod
    def find_path(cls: Type[BaseView], base: Type[BaseView], path=None):
        if not path:
            path = []

        if cls == base:
            return path

        path = path + [base]

        for subcls in BaseView._inner_classes_list(base):
            subpath = DisambiguationView.find_path(cls, subcls, path)
            if subpath:
                return subpath

        return None

    @staticmethod
    def generate_ul(cls: Type[BaseView], url_base=""):
        if not url_base:
            path = DisambiguationView.find_path(cls, Index)
            path += [cls]

            for item in path:
                url_base += f"{item.url_name()}{'/' if item.url_name() else ''}"

        subs = BaseView._inner_classes_list(cls, True)
        ul = '<ul>'
        if subs:
            for sub in subs:
                rev = sub.own_url_name(url_base)
                ul += f'<li><a href="{reverse(rev)}">{sub.name()}</a>'
                ul += DisambiguationView.generate_ul(sub, f"{url_base}{sub.url_name()}{'/' if sub.url_name() else ''}")
                ul += '</li>'
        ul += '</ul>'
        return ul

    @staticmethod
    def generate_breadcrumbs(cls: Type[BaseView], base: Type[BaseView]):
        path = DisambiguationView.find_path(cls, base)
        breadcrumbs = []
        url_name_base = ""

        for item in path:
            breadcrumbs.append((item.name(), item.own_url_name(url_name_base)))
            url_name_base += f"{item.url_name()}{'/' if item.url_name() else ''}"

        breadcrumbs.append((cls.name(), ""))

        return breadcrumbs


@login_required
def index(request):
    if request.user.is_waiter:
        return redirect(reverse("waiter/tabs"))
    elif request.user.is_manager:
        return redirect(reverse("manager/tills"))
    elif request.user.is_director:
        return redirect(reverse("director/menu/products"))


class Index(LoginRequiredMixin, DisambiguationView):
    _name = "Home"
    _url = ""
    _url_name = ""
    _own_url_name = "index"

    class Waiter(WaiterLoginRequiredMixin, DisambiguationView):
        class Tabs(WaiterLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "waiter/tabs/index.html", "Tabs")
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
                _url = "<uuid:id>"
                _advertise = False
                template_name = "waiter/tabs/tab.html"

                def get(self, id, *args, **kwargs):
                    self.next_url = reverse("waiter/tabs/tab", kwargs={"id": id})
                    try:
                        tab = Tab.objects.filter(temp_tab_owner__isnull=True).get(id=id)
                        context = self.fill_data(tab)
                        return context.render()
                    except Tab.DoesNotExist:
                        return ErrorView(self.request, 404, title="Tab").render()

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
                                    messages.success(self.request,
                                                     f"A transfer to user {new_owner.name} was requested.")
                                else:
                                    messages.warning(self.request,
                                                     f"Only the tab owner can request transfers to another user.")
                            except Tab.DoesNotExist:
                                return ErrorView(self.request, 404, title="Tab").render()
                            except User.DoesNotExist:
                                messages.error(self.request,
                                               "Can't transfer tab: the requested new owner does not exist.")
                            except ValidationError as err:
                                return ErrorView(self.request, 500,
                                                 comment=f"Request creation failed: {err.message}").render()
                        else:
                            messages.warning(self.request,
                                             "newOwnerUsername parameter was missing. Please try it again.")
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
                            return ErrorView(self.request, 404, title="Tab").render()
                        except ValidationError as err:
                            return ErrorView(self.request, 500,
                                             comment=f"Request creation failed: {err.message}").render()
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
                                return ErrorView(self.request, 404, title="Tab").render()
                            except User.DoesNotExist:
                                messages.error(self.request,
                                               "Can't change tab owner: the requested new owner does not exist.")
                            except ValidationError as err:
                                return ErrorView(self.request, 500,
                                                 comment=f"Owner change failed: {err.message}").render()
                        else:
                            messages.warning(self.request,
                                             "newOwnerUsername parameter was missing. Please try it again.")
                        return redirect(reverse("waiter/tabs/tab", kwargs={"id": id}))

        class Orders(WaiterLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "waiter/orders/index.html", "Orders")
                context["waiting"] = ProductInTab.objects.filter(state=ProductInTab.ORDERED).order_by("orderedAt")
                context["preparing"] = ProductInTab.objects.filter(state=ProductInTab.PREPARING).order_by("preparingAt")
                context["prepared"] = ProductInTab.objects.filter(state=ProductInTab.TO_SERVE).order_by("preparedAt")
                context["served"] = ProductInTab.objects.filter(state=ProductInTab.SERVED).order_by("orderedAt")
                return context.render()

            class Order(WaiterLoginRequiredMixin, BaseView):
                _url = "<uuid:id>"
                _advertise = False

                def get(self, id, *args, **kwargs):
                    messages.info(self.request, "Well that was disappointing...")
                    return redirect(reverse("waiter/orders"))

                class Bump(WaiterLoginRequiredMixin, BaseView):
                    _url = "bump/<int:count>"

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
                            return ErrorView(self.request, 404, title="Order").render()
                        except ValidationError as err:
                            return ErrorView(self.request, 500, comment=err.message).render()
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
                            return ErrorView(self.request, 500, comment=err.message).render()
                        except ProductInTab.DoesNotExist:
                            return ErrorView(self.request, 404, title="Order").render()
                        return redirect(
                            self.request.GET["next"] if "next" in self.request.GET else reverse("waiter/orders"))

                class Void(ManagerLoginRequiredMixin, BaseView):
                    def get(self, id, *args, **kwargs):
                        try:
                            order = ProductInTab.objects.get(id=id)
                            order.void()
                            messages.success(self.request, f"Order of a {order.product.name} voided")
                        except ProductInTab.DoesNotExist:
                            return ErrorView(self.request, 404, title="Order").render()
                        except ValidationError as err:
                            return ErrorView(
                                self.request, 500,
                                comment=f"Failed voiding order of {order.product.name}: {err.message}"
                            ).render()
                        return redirect(
                            self.request.GET["next"] if "next" in self.request.GET else reverse("waiter/orders"))

                class AuthenticateAndVoid(WaiterLoginRequiredMixin, BaseView):
                    def get(self, id, *args, **kwargs):
                        context = Context(self.request, "waiter/orders/order/authenticateAndVoid.html",
                                          "Order void authentication")
                        try:
                            context["id"] = id
                            context["order"] = ProductInTab.objects.get(id=id)
                            context["form"] = AuthenticationForm()
                            if "next" in self.request.GET:
                                context["next"] = self.request.GET["next"]
                            return context.render()
                        except ProductInTab.DoesNotExist:
                            return ErrorView(self.request, 404, title="Order").render()

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
                                return ErrorView(self.request, 404, title="Order").render()
                            except ValidationError as err:
                                return ErrorView(
                                    self.request, 500,
                                    comment=f"Failed voiding order of {order.product.name}: {err.message}"
                                ).render()
                        else:
                            messages.error(self.request, "Username or password was missing in the self.request")

                        return redirect(
                            self.request.GET["next"] if "next" in self.request.GET else reverse("waiter/orders"))

        class Direct(WaiterLoginRequiredMixin, BaseView):
            _name = "Direct order"

            def get(self, *args, **kwargs):
                if self.request.user.current_temp_tab:
                    return redirect(reverse("waiter/direct/order"))
                else:
                    return redirect(reverse("waiter/direct/new"))

            class New(WaiterLoginRequiredMixin, BaseView):
                def get(self, *args, **kwargs):
                    context = Context(self.request, "waiter/direct/new.html", "New direct order")
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
                        return ErrorView(self.request, 500,
                                         comment="Something went wrong when starting order: " + err.message).render()
                    return redirect(reverse("waiter/direct"))

            class Order(WaiterLoginRequiredMixin, BaseView):
                def get(self, *args, **kwargs):
                    context = Context(self.request, "waiter/direct/order.html", "Direct order")
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

        class CurrentMembers(WaiterLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "waiter/current_members.html","Current Members")
                search = self.request.GET.get('search', '')
                members = Member.objects.filter(membership_status=Member.ACTIVE)

                if search:
                    members = members.filter(
                        Q(first_name__icontains=search) |
                        Q(last_name__icontains=search)
                        )

                context.add_pagination_context(members, "members")
                context["search"] = search

                return context.render()

    class Manager(ManagerLoginRequiredMixin, DisambiguationView):
        class Users(ManagerLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "manager/users/index.html", "Users")
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

            class Create(ManagerLoginRequiredMixin, BaseView):
                _name = "Create user"

                def get(self, *args, **kwargs):
                    context = Context(self.request, "manager/users/create.html", "Create new user")
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
                        messages.success(self.request,
                                         f"The user {form.cleaned_data['username']} was created successfully")
                        return redirect(reverse("manager/users"))

                    context = Context(self.request, "manager/users/create.html", "Create new user")
                    context["form"] = form
                    return context.render()

            class User(ManagerLoginRequiredMixin, BaseView):
                _url = "<str:username>"
                _advertise = False

                def get(self, username, *args, **kwargs):
                    context = Context(self.request, "manager/users/user.html")
                    try:
                        user = User.objects.get(username=username)
                        context["user"] = user
                        context.title = str(user)
                        if username == self.request.user.username:
                            context["password_change_blocked"] = 1
                        elif not self.request.user.can_change_password(user):
                            context["password_change_blocked"] = 2
                        else:
                            context["password_change_blocked"] = 0
                    except User.DoesNotExist:
                        return ErrorView(self.request, 404, title="User").render()
                    return context.render()

                def post(self, username, *args, **kwargs):
                    context = Context(self.request, "manager/users/user.html")
                    try:
                        user = User.objects.get(username=username)
                        context.title = str(user)
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
                        return ErrorView(self.request, 404, title="User").render()
                    return context.render()

        class Tills(ManagerLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "manager/tills/index.html", "Tills")
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
                _name = "Assign till"

                def get(self, *args, **kwargs):
                    context = Context(self.request, "manager/tills/assign.html", "Assign till")

                    context["users"] = User.objects.filter(is_waiter=True, current_till=None)
                    context["options"] = Deposit.objects.filter(enabled=True)

                    return context.render()

                def post(self, *args, **kwargs):
                    context = Context(self.request, "manager/tills/assign.html", "Assign till")
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
                            return ErrorView(self.request, 500,
                                             comment=f"Failed creating the Till: {err.message}").render()
                    else:
                        messages.error(self.request, "Some required fields are missing")

                    context["users"] = User.objects.filter(is_waiter=True, current_till=None)
                    context["options"] = Deposit.objects.filter(enabled=True)

                    return context.render()

            class Till(ManagerLoginRequiredMixin, BaseView):
                _url = "<uuid:id>"
                _advertise = False

                def get(self, id, *args, **kwargs):
                    context = Context(self.request, "manager/tills/till/index.html", "Till details")
                    try:
                        till = Till.objects.get(id=id)
                        if till.state != Till.COUNTED:
                            return ErrorView(
                                self.request, 403,
                                comment=f"It is not allowed to display a till in the state {till.get_state_display()}"
                            ).render()
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

                            for edit in count.tilledit_set.order_by('transaction__timestamp').all():
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
                        return ErrorView(self.request, 404, title="Till").render()
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
                            return ErrorView(self.request, 404, title="Till").render()
                        except ValidationError as err:
                            return ErrorView(self.request, 500, comment=f"Failed stopping Till: {err.message}").render()
                        return redirect(reverse("manager/tills"))

                class Count(ManagerLoginRequiredMixin, BaseView):
                    def get(self, id, zeroed=None, *args, **kwargs):
                        context = Context(self.request, "manager/tills/till/count.html", "Count till")
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
                            return ErrorView(self.request, 404, title="Till").render()
                        except KeyError:
                            messages.error(self.request, "One of the counts required was missing in the request. "
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
                            return ErrorView(self.request, 404, title="Till").render()
                        except ValidationError as err:
                            return ErrorView(self.request, 500, comment=f"Failed closing Till: {err.message}").render()
                        return redirect(reverse("manager/tills"))

                class Edit(ManagerLoginRequiredMixin, BaseView):
                    def get(self, id, *args, **kwargs):
                        context = Context(self.request, "manager/tills/till/edit.html", "Edit till")
                        try:
                            till = Till.objects.get(id=id)
                            if till.state != Till.COUNTED:
                                return ErrorView(
                                    self.request, 403,
                                    comment=f"It is not allowed to edit a till in the state {till.get_state_display()}"
                                ).render()
                            context["id"] = id
                            context["counts"] = till.tillmoneycount_set.all()
                        except Till.DoesNotExist:
                            return ErrorView(self.request, 404, title="Till").render()

                        return context.render()

                    def post(self, id, *args, **kwargs):
                        context = Context(self.request, "manager/tills/till/edit.html", "Edit till")
                        try:
                            till = Till.objects.get(id=id)
                            if till.state != Till.COUNTED:
                                return ErrorView(
                                    self.request, 403,
                                    comment=f"It is not allowed to edit a till in the state {till.get_state_display()}"
                                ).render()
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
                                    messages.warning(self.request,
                                                     'The specified payment method does not exist in this '
                                                     'till. Please try again.')
                                except ValidationError as err:
                                    messages.error(self.request, f"Creating Till edit failed: {err.message}")
                            context["id"] = id
                            context["counts"] = till.tillmoneycount_set.all()
                        except Till.DoesNotExist:
                            return ErrorView(self.request, 404, title="Till").render()

                        return context.render()

        class Requests(ManagerLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "manager/requests/index.html", "Requests")
                context["void_requests_open"] = OrderVoidRequest.objects.filter(resolution__isnull=True)
                context["transfer_requests_open"] = TabTransferRequest.objects.all()
                return context.render()

            class Void(ManagerLoginRequiredMixin, BaseView):
                _name = "Void requests"

                def get(self, *args, **kwargs):
                    context = Context(self.request, "manager/requests/void.html", "Void requests")
                    context["void_requests_open"] = OrderVoidRequest.objects.filter(resolution__isnull=True)
                    context.add_pagination_context(OrderVoidRequest.objects.exclude(resolution__isnull=True),
                                                   "closed_requests")
                    return context.render()

                class Resolve(ManagerLoginRequiredMixin, BaseView):
                    _url = "<uuid:id>/<str:resolution>"
                    _url_name = "request/resolve"
                    _advertise = False

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
                                return ErrorView(self.request, 404, title="Void request").render()
                            except ValidationError as err:
                                return ErrorView(self.request, 500,
                                                 comment=f"Resolving void request failed: {err.message}").render()

                        return redirect(reverse("manager/requests/void"))

            class Transfer(ManagerLoginRequiredMixin, BaseView):
                _name = "Transfer requests"
                _advertise = False

                def get(self, *args, **kwargs):
                    return redirect(reverse("manager/requests"))

                class Resolve(ManagerLoginRequiredMixin, BaseView):
                    _url = "<uuid:id>/<str:resolution>"
                    _url_name = "request/resolve"

                    def get(self, id, resolution, *args, **kwargs):
                        if resolution not in ["approve", "reject"]:
                            return ErrorView(self.request, 400,
                                             comment=f"The specified resolution '{resolution}' is not valid. "
                                                     f"It must be either approve or reject.").render()
                        else:
                            try:
                                transfer_request = TabTransferRequest.objects.get(id=id)
                                if resolution == "approve":
                                    transfer_request.approve(self.request.user)
                                    messages.success(self.request,
                                                     f"The request from {transfer_request.requester.name} "
                                                     f"to transfer tab {transfer_request.tab.name} to "
                                                     f"{transfer_request.new_owner.name} was approved.")
                                elif resolution == "reject":
                                    transfer_request.reject(self.request.user)
                                    messages.success(self.request,
                                                     f"The request from {transfer_request.requester.name} "
                                                     f"to transfer tab {transfer_request.tab.name} to "
                                                     f"{transfer_request.new_owner.name} was rejected.")
                            except TabTransferRequest.DoesNotExist:
                                return ErrorView(self.request, 404, title="Tab transfer request").render()
                            except ValidationError as err:
                                return ErrorView(self.request, 500,
                                                 comment=f"Resolving transfer request failed: {err.message}").render()

                        return redirect(reverse("manager/requests/transfer"))

        class Expenses(ManagerLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "manager/expenses/index.html", "Expenses")
                username_filter = self.request.GET.get('username', '')
                state_filter = self.request.GET.get('state', '')

                context["state_options"] = [{"value": value, "display": display} for value, display in Expense.STATES]
                if self.request.user.is_director:
                    expenses = Expense.objects.all()
                    context["user_options"] = [{"username": username, "name": name} for username, name in set(
                        (expense.requested_by.username, expense.requested_by.name) for expense in expenses)]
                else:
                    expenses = Expense.objects.filter(requested_by=self.request.user)

                if username_filter:
                    expenses = expenses.filter(requested_by__username=username_filter)
                if state_filter:
                    expenses = expenses.filter(state=state_filter)
                expenses = expenses.order_by("state_sort", "requested_at")

                context.add_pagination_context(expenses, "expenses")
                for expense in context["expenses"]["data"]:
                    expense.set_transition_permissions(self.request.user)

                context["user_filter"] = username_filter
                context["state_filter"] = state_filter
                return context.render()

            class Expense(ManagerLoginRequiredMixin, BaseView):
                _url = "<uuid:id>"
                _advertise = False

                def get(self, id=None, form=None, *args, **kwargs):
                    context = Context(self.request, "manager/expenses/expense.html", "Expense details")
                    if id:
                        try:
                            expense = Expense.objects.get(id=id)
                            context["invoice_file_type"] = expense.invoice_file_type
                            expense.set_transition_permissions(self.request.user)
                            context["expense"] = expense
                            if self.request.user.is_director:
                                context["is_review"] = True
                            if expense.requested_by == self.request.user and expense.is_editable:
                                context["is_edit"] = True
                                context["form"] = form or CreateEditExpenseForm(instance=expense)
                            if not self.request.user.is_director and not expense.requested_by == self.request.user:
                                messages.warning(self.request,
                                                 "You need to be a director to access someone else's expense")
                                return redirect(reverse("manager/expenses"))

                            log_items = StateLog.objects.for_(expense)
                            timeline = []
                            for item in log_items:
                                ti = TimelineItem(item.timestamp)
                                if item.state == Expense.REQUESTED:
                                    ti.icon = '''
                                    <i class="bg-primary ion fa-layers">
                                        <i class="far fa-comment-alt" data-fa-transform="right-0.5"></i>
                                        <i class="fas fa-question" data-fa-transform="shrink-8 up-1.5"></i>
                                    </i>
                                    '''
                                    ti.header = f'<a href="#">{item.by.name}</a> submitted this expense for review'
                                elif item.state == Expense.ACCEPTED:
                                    ti.icon = '''
                                    <i class="bg-success ion fa-layers">
                                        <i class="far fa-comment-alt" data-fa-transform="right-0.5 flip-h"></i>
                                        <i class="fas fa-check" data-fa-transform="shrink-8 up-1.5 right-0.8"></i>
                                    </i>
                                    '''
                                    ti.header = f'<a href="#">{item.by.name}</a> accepted this expense'
                                elif item.state == Expense.REJECTED:
                                    ti.icon = '''
                                    <i class="bg-danger ion fa-layers">
                                        <i class="far fa-comment-alt" data-fa-transform="right-0.5 flip-h"></i>
                                        <i class="fas fa-times" data-fa-transform="shrink-8 up-1.5 right-0.8"></i>
                                    </i>
                                    '''
                                    ti.header = f'<a href="#">{item.by.name}</a> rejected this expense'
                                    ti.body = item.description
                                elif item.state == Expense.APPEALED:
                                    ti.icon = '''
                                    <i class="bg-warning ion fa-layers">
                                        <i class="far fa-comment-alt" data-fa-transform="right-0.5"></i>
                                        <i class="fas fa-exclamation" data-fa-transform="shrink-8 up-1.5"></i>
                                    </i>
                                    '''
                                    ti.header = f'<a href="#">{item.by.name}</a> appealed the rejection'
                                    ti.body = item.description
                                elif item.state == Expense.PAID:
                                    ti.icon = '''
                                    <i class="bg-info ion fa-layers">
                                        <i class="far fa-comment-alt" data-fa-transform="right-0.5 flip-h"></i>
                                        <i class="fas fa-dollar-sign" data-fa-transform="shrink-8 up-1.5 right-0.8"></i>
                                    </i>
                                    '''
                                    ti.header = f'<a href="#">{item.by.name}</a> paid this expense'
                                timeline.append(ti)
                            ti = TimelineItem(expense.requested_at)
                            ti.icon_classes = 'bg-secondary fas fa-asterisk'
                            ti.header = f'<a href="#">{expense.requested_by.name}</a> created this expense'
                            timeline.append(ti)
                            context.add_timeline_context(timeline, "timeline", 'bg-info')
                            return context.render()
                        except Expense.DoesNotExist:
                            return ErrorView(self.request, 404, title="Expense").render()
                    else:
                        context["form"] = form or CreateEditExpenseForm()
                        context["header"] = "Create expense"
                        context["is_create"] = True
                        return context.render()

                def post(self, id=None, *args, **kwargs):
                    if id:
                        expense = Expense.objects.filter(id=id).first()
                    else:
                        expense = Expense()
                        expense.requested_by = self.request.user

                    form = None
                    if expense:
                        if expense.requested_by == self.request.user and expense.is_editable:
                            form = CreateEditExpenseForm(self.request.POST, instance=expense)
                            if form.is_valid():
                                form.save()
                                messages.success(self.request, "Expense updated")
                                return redirect(reverse("manager/expenses/expense", kwargs={"id": expense.id}))
                        else:
                            messages.error(self.request,
                                           "Only the expense owner may edit it, and only in editable states")
                    return self.get(id, form, *args, **kwargs)

                class InvoiceFile(ManagerLoginRequiredMixin, BaseView):
                    def get(self, id, *args, **kwargs):
                        try:
                            expense = Expense.objects.get(id=id)
                            if self.request.user.is_director or expense.requested_by == self.request.user:
                                file_path = os.path.join(settings.MEDIA_ROOT, expense.invoice_file.name)
                                if os.path.exists(file_path):
                                    with open(file_path, 'rb') as f:
                                        response = HttpResponse(f.read(),
                                                                content_type=mimetypes.guess_type(
                                                                    expense.invoice_file.name)[0])
                                        name = expense.invoice_file.name.split('/')[-1]
                                        response['Content-Disposition'] = f'inline;filename={name}'
                                        return response
                            else:
                                messages.warning(self.request,
                                                 "You need to be a director to access someone else's expense")
                        except Expense.DoesNotExist:
                            return ErrorView(self.request, 404, title="Expense").render()
                        return redirect(reverse("manager/expenses"))

                    def post(self, id, *args, **kwargs):
                        try:
                            expense = Expense.objects.get(id=id)
                            if expense.requested_by == self.request.user and expense.is_editable:
                                if "invoice_file" in self.request.FILES:
                                    invoice_file = self.request.FILES["invoice_file"]
                                    data = io.BytesIO(invoice_file.read())
                                    try:
                                        Image.open(data)
                                        expense.invoice_file = invoice_file
                                        expense.clean()
                                        expense.save()
                                        messages.success(self.request, "Image uploaded successfully, see for yourself")
                                    except UnidentifiedImageError:
                                        try:
                                            PdfFileReader(data)
                                            expense.invoice_file = invoice_file
                                            expense.clean()
                                            expense.save()
                                            messages.success(self.request, "PDF uploaded successfully")
                                        except PdfReadError:
                                            messages.error(self.request,
                                                           "Only image or PDF files are allowed. Upload one of those")
                                else:
                                    messages.warning(self.request,
                                                     "The file was missing in the request. Please try it again.")
                            else:
                                messages.error(self.request,
                                               "Only the expense owner may edit it, and only in editable states")
                            return redirect(reverse("manager/expenses/expense", kwargs={"id": id}))
                        except Expense.DoesNotExist:
                            return ErrorView(self.request, 404, title="Expense").render()
                        except ValidationError as err:
                            return ErrorView(self.request, 500,
                                             comment=f"Something went wrong while saving the file: {err.message}").render()

                class Transition(ManagerLoginRequiredMixin, BaseView):
                    _url = "<exp_tr:transition>"
                    _url_name = "transition"

                    def post(self, id, transition, *args, **kwargs):
                        try:
                            expense = Expense.objects.get(id=id)
                            transition_method = getattr(expense, transition)

                            if has_transition_perm(transition_method, self.request.user):
                                with atomic():
                                    transition_method(by=self.request.user,
                                                      description=self.request.POST.get('description', ''))
                                    expense.clean()
                                    expense.save()
                                    messages.success(self.request, "Expense state updated")
                            else:
                                messages.warning(self.request,
                                                 f"You don't have permission to perform {transition} on this expense or "
                                                 "its state does not allow it.")
                        except Expense.DoesNotExist:
                            return ErrorView(self.request, 404, title="Expense").render()
                        except ValidationError as err:
                            return ErrorView(self.request, 500, comment=err.message).render()

                        return redirect(reverse("manager/expenses/expense", kwargs={"id": id}))

            class Create(Expense):
                _url = "create"

    class Director(DirectorLoginRequiredMixin, DisambiguationView):
        class Finance(DirectorLoginRequiredMixin, DisambiguationView):
            class Currencies(DirectorLoginRequiredMixin, BaseView):
                def get(self, *args, **kwargs):
                    context = Context(self.request, "director/finance/currencies.html", "Currencies")
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
                _name = "Payment methods"

                def get(self, form=None, show_modal=False, *args, **kwargs):
                    context = Context(self.request, "director/finance/methods.html", "Payment methods")

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
                    _url = "<uuid:id>"
                    _advertise = False

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
                                return ErrorView(self.request, 404, title="Payment").render()
                            except ProtectedError:
                                return ErrorView(self.request, 403,
                                                 comment="The specified method can't be deleted as other records such as "
                                                         "payments or tills depend on it. You can remove it from the "
                                                         "deposits to prevent further use.").render()
                            return redirect(reverse("director/finance/methods"))

            class Deposits(DirectorLoginRequiredMixin, BaseView):

                def get(self, *args, **kwargs):
                    context = Context(self.request, 'director/finance/deposits/index.html', "Deposits")
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
                            return ErrorView(self.request, 404, title="Deposit").render()
                    return self.get(self.request)

                class Edit(DirectorLoginRequiredMixin, BaseView):
                    _url = "<uuid:id>"
                    _url_name = "deposit"
                    _advertise = False

                    def get(self, id=None, *args, **kwargs):
                        context = Context(self.request, 'director/finance/deposits/edit.html')
                        context['id'] = id
                        if id:
                            context['is_edit'] = True
                            try:
                                deposit = Deposit.objects.get(id=id)
                                context['form'] = CreateEditDepositForm(instance=deposit)
                                context.title = str(deposit)
                            except Deposit.DoesNotExist:
                                return ErrorView(self.request, 404, title="Deposit").render()
                        else:
                            context['form'] = CreateEditDepositForm()
                            context.title = "Create new deposit"
                        return context.render()

                    def post(self, id=None, *args, **kwargs):
                        context = Context(self.request, 'director/finance/deposits/edit.html')
                        context['id'] = id
                        if id:
                            context['is_edit'] = True
                            try:
                                deposit = Deposit.objects.get(id=id)
                                context.title = str(deposit)
                            except Deposit.DoesNotExist:
                                return ErrorView(self.request, 404, title="Deposit").render()
                        else:
                            deposit = Deposit()
                            context.title = "Create new deposit"

                        form = CreateEditDepositForm(self.request.POST, instance=deposit)
                        if form.is_valid():
                            form.save()
                            messages.success(self.request, "Deposit saved successfully!")
                            return redirect(reverse('director/finance/deposits'))
                        else:
                            context['form'] = form
                            return context.render()

                class Create(Edit):
                    _url = "create"
                    _url_name = "create"

        class Units(DirectorLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, 'director/units/index.html', "Units")
                context['groups'] = UnitGroup.objects.all()

                return context.render()

            def post(self, *args, **kwargs):
                context = Context(self.request, 'director/units/index.html', "Units")
                if check_dict(self.request.POST, ['newUnitGroupName', 'newUnitGroupSymbol']):
                    group = UnitGroup()
                    group.name = self.request.POST['newUnitGroupName']
                    group.symbol = self.request.POST['newUnitGroupSymbol']
                    try:
                        group.clean()
                        group.save()
                        messages.success(self.request, "The unit group was created successfully")
                    except ValidationError as err:
                        return ErrorView(self.request, 500, comment=err.message).render()
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
                            return ErrorView(self.request, 500, comment=err.message).render()
                    except UnitGroup.DoesNotExist:
                        return ErrorView(self.request, 404, title="Unit group").render()

                if 'deleteUnitId' in self.request.POST:
                    try:
                        unit = Unit.objects.get(id=uuid.UUID(self.request.POST['deleteUnitId']))
                        unit.delete()
                        messages.success(self.request, "The unit was deleted successfully")
                    except Unit.DoesNotExist:
                        return ErrorView(self.request, 404, title="Unit").render()
                if 'deleteUnitGroupId' in self.request.POST:
                    try:
                        group = UnitGroup.objects.get(id=uuid.UUID(self.request.POST['deleteUnitGroupId']))
                        group.delete()
                        messages.success(self.request, "The unit group was deleted successfully")
                    except UnitGroup.DoesNotExist:
                        return ErrorView(self.request, 404, title="Unit group").render()
                    except ProtectedError:
                        return ErrorView(self.request, 500,
                                         comment="Deletion failed: an Item depends on this Unit Group!") \
                            .render()
                context['groups'] = UnitGroup.objects.all()

                return context.render()

        class Menu(DirectorLoginRequiredMixin, DisambiguationView):
            class Products(DirectorLoginRequiredMixin, BaseView):
                def fill_data(self, request):
                    context = Context(self.request, 'director/menu/products/index.html', "Products")
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
                    _url = "<uuid:id>"
                    _advertise = False

                    def get(self, id, *args, **kwargs):
                        context = Context(self.request, 'director/menu/products/product.html')
                        context["id"] = id
                        try:
                            product = Product.objects.get(id=id)
                            form = CreateEditProductForm(instance=product)
                            items_formset = ItemsInProductFormSet(
                                queryset=ItemInProduct.objects.filter(product=product))
                            context["form"] = form
                            context["items_formset"] = items_formset
                            context["show_form"] = True
                            context.title = str(product)
                        except Product.DoesNotExist:
                            return ErrorView(self.request, 404, title="Product").render()
                        return context.render()

                    def post(self, id, *args, **kwargs):
                        context = Context(self.request, 'director/menu/products/product.html')
                        context["id"] = id
                        try:
                            product = Product.objects.get(id=id)
                            context.title = str(product)
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
                            return ErrorView(self.request, 404, title="Product").render()
                        return context.render()

                    class Delete(DirectorLoginRequiredMixin, BaseView):
                        def get(self, id, *args, **kwargs):
                            try:
                                product = Product.objects.get(id=id)
                                product.delete()
                                messages.success(self.request, f"Product {product.name} was deleted.")
                                return redirect(reverse("director/menu/products"))
                            except Product.DoesNotExist:
                                return ErrorView(self.request, 404, title="Product").render()
                            except ProtectedError:
                                return ErrorView(self.request, 403,
                                                 comment="This Product can't be deleted as it was already ordered").render()

            class Items(BaseView):
                def fill_data(self, request):
                    context = Context(self.request, 'director/menu/items/index.html', "Items")
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
                    _url = "<uuid:id>"
                    _advertise = False

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
                                return ErrorView(self.request, 404, title="Item").render()
                            except ProtectedError:
                                return ErrorView(
                                    self.request, 403,
                                    comment="The item can't be deleted because it is used by a Product"
                                ).render()
                            return redirect(reverse('director/menu/items'))

        class Members(DirectorLoginRequiredMixin, BaseView):
            def get(self, *args, **kwargs):
                context = Context(self.request, "director/members/index.html", "Members")
                search = self.request.GET.get('search', '')
                membership_status_filter = self.request.GET.get('membership_status', '')

                members = Member.objects.all()
                if search:
                    members = members.filter(
                        Q(first_name__icontains=search) |
                        Q(last_name__icontains=search) |
                        Q(email__icontains=search)
                    )
                if membership_status_filter:
                    members = members.filter(membership_status=membership_status_filter)
                context.add_pagination_context(members, "members")

                context["membership_status_options"] = [{"value": value, "display": display} for value, display in
                                                        Member.MEMBERSHIP_STATES]
                context["membership_status_filter"] = membership_status_filter
                context["search"] = search

                return context.render()

            class Member(DirectorLoginRequiredMixin, BaseView):
                _url = "<uuid:id>"
                _advertise = False

                def get(self, id=None, form=None, *args, **kwargs):
                    context = Context(self.request, "director/members/member.html")

                    if id:
                        try:
                            member = Member.objects.get(id=id)
                            member.set_transition_permissions(self.request.user)
                            context["member"] = member
                            context.title = member.full_name
                            context["form"] = form or CreateEditMemberForm(instance=member)

                            log_items = StateLog.objects.for_(member)
                            timeline = []
                            for item in log_items:
                                ti = TimelineItem(item.timestamp)
                                if item.state == Member.NEW:
                                    ti.icon_classes = 'fas fa-plus bg-primary'
                                    ti.header = f'<a href="#">{item.by.name}</a> created member {member.full_name}'
                                elif item.state == Member.ACTIVE:
                                    ti.icon_classes = 'fas fa-play bg-success'
                                    if item.transition == "accept":
                                        ti.header = f'<a href="#">{item.by.name}</a> accepted {member.full_name}\'s ' \
                                                    'membership request'
                                    elif item.transition == "restore":
                                        ti.header = f'<a href="#">{item.by.name}</a> restored {member.full_name}\'s ' \
                                                    'membership'
                                    if item.description:
                                        ti.header += ' with the following note:'
                                        ti.body = item.description
                                elif item.state == Member.SUSPENDED:
                                    ti.icon_classes = 'fas fa-pause bg-warning'
                                    ti.header = f'<a href="#">{item.by.name}</a> suspended {member.full_name}\'s ' \
                                                'membership due to the following reason:'
                                    ti.body = item.description
                                elif item.state == Member.TERMINATED:
                                    if item.transition == "reject":
                                        ti.icon_classes = 'fas fa-ban bg-danger'
                                        ti.header = f'<a href="#">{item.by.name}</a> rejected {member.full_name}\'s ' \
                                                    'membership request with the following reason:'
                                    elif item.transition == "terminate":
                                        ti.icon_classes = 'fas fa-stop bg-danger'
                                        ti.header = f'<a href="#">{item.by.name}</a> terminated {member.full_name}\'s ' \
                                                    'membership due to the following reason:'
                                    ti.body = item.description
                                timeline.append(ti)
                            ti = TimelineItem(
                                datetime.datetime(member.created_at.year, member.created_at.month,
                                                  member.created_at.day,
                                                  tzinfo=pytz.UTC))
                            ti.icon_classes = 'bg-primary fas fa-asterisk'
                            ti.header = f'<a href="#">{member.full_name}</a> requested membership'
                            timeline.append(ti)
                            context.add_timeline_context(timeline, "timeline", 'bg-info')
                        except Member.DoesNotExist:
                            return ErrorView(self.request, 404, title="Member")
                    else:
                        context["form"] = form or CreateEditMemberForm()
                        context.title = "Create member"

                    return context.render()

                def post(self, id=None, *args, **kwargs):
                    if id:
                        try:
                            member = Member.objects.get(id=id)
                        except Member.DoesNotExist:
                            return ErrorView(self.request, 404, title="Member")
                    else:
                        member = Member()

                    form = CreateEditMemberForm(self.request.POST, instance=member)
                    if form.is_valid():
                        form.save()
                        form = None

                    if id or form:
                        print(self.request.POST.get('birth_date', 'not-found'))
                        return self.get(id, form, *args, **kwargs)
                    else:
                        return redirect(reverse("director/members/member", kwargs={"id": member.id}))

                class MembershipTransition(DirectorLoginRequiredMixin, BaseView):
                    _url = "<mss_tr:transition>"
                    _url_name = "membership"

                    def post(self, id, transition, *args, **kwargs):
                        try:
                            member = Member.objects.get(id=id)
                            transition_method = getattr(member, transition)

                            if has_transition_perm(transition_method, self.request.user):
                                with atomic():
                                    transition_method(by=self.request.user,
                                                      description=self.request.POST.get('description', ''))
                                    member.clean()
                                    member.save()
                                    messages.success(self.request, "Membership status updated")
                            else:
                                messages.warning(self.request,
                                                 f"You don't have permission to perform {transition} on this member or "
                                                 "its state does not allow it.")
                        except Member.DoesNotExist:
                            return ErrorView(self.request, 404, title="Member")
                        except ValidationError as err:
                            return ErrorView(self.request, 500, comment=err.message).render()

                        return redirect(reverse('director/members/member', kwargs={'id': id}))

                class ApplicationFile(DirectorLoginRequiredMixin, BaseView):
                    def get(self, id, *args, **kwargs):
                        try:
                            member = Member.objects.get(id=id)
                            file_path = os.path.join(settings.MEDIA_ROOT, member.application_file.name)
                            if os.path.exists(file_path):
                                with open(file_path, 'rb') as f:
                                    response = HttpResponse(f.read(),
                                                            content_type=mimetypes.guess_type(
                                                                member.application_file.name)[0])
                                    name = member.application_file.name.split('/')[-1]
                                    response['Content-Disposition'] = f'inline;filename={name}'
                                    return response
                            else:
                                return ErrorView(self.request, 500,
                                                 comment="The file that was supposed to be there is missing. Information "
                                                         f"for adminstrator: file path {file_path}").render()
                        except Expense.DoesNotExist:
                            return ErrorView(self.request, 404, title="Member").render()

                    def post(self, id, *args, **kwargs):
                        try:
                            member = Member.objects.get(id=id)
                            if member.membership_status != Member.NEW:
                                return ErrorView(self.request, 403,
                                                 comment="New application file may only be uploaded for "
                                                         "new members").render()
                            if "application_file" in self.request.FILES:
                                application_file = self.request.FILES["application_file"]
                                data = io.BytesIO(application_file.read())
                                try:
                                    Image.open(data)
                                    member.application_file = application_file
                                    member.clean()
                                    member.save()
                                    messages.success(self.request, "Image uploaded successfully, see for yourself")
                                except UnidentifiedImageError:
                                    try:
                                        PdfFileReader(data)
                                        member.application_file = application_file
                                        member.clean()
                                        member.save()
                                        messages.success(self.request, "PDF uploaded successfully")
                                    except PdfReadError:
                                        messages.error(self.request,
                                                       "Only image or PDF files are allowed. Upload one of those")
                            else:
                                messages.warning(self.request,
                                                 "The file was missing in the request. Please try it again.")
                            return redirect(reverse("director/members/member", kwargs={"id": id}))
                        except Expense.DoesNotExist:
                            return ErrorView(self.request, 404, title="Member").render()
                        except ValidationError as err:
                            return ErrorView(self.request, 500,
                                             comment=f"Something went wrong while saving the file: {err.message}").render()

            class Create(Member):
                _url = "create"

    class Debug(DisambiguationView):
        _advertise = bool(settings.DEBUG)

        class CreateUser(BaseView):
            _name = "Create user"
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
