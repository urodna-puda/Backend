import io
import mimetypes
import os
import re
from datetime import datetime
from uuid import uuid4

from PIL import Image
from PyPDF2 import PdfFileReader
from PyPDF2.utils import PdfReadError
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.dispatch import receiver
from django.urls import reverse
from django_countries.fields import CountryField
from django_fsm import FSMField, transition, ConcurrentTransitionMixin, has_transition_perm
from django_fsm_log.decorators import fsm_log_by, fsm_log_description
from phonenumber_field.modelfields import PhoneNumberField


# Create your models here.

def action(group="state"):
    def action_decorator(method):
        def wrapper(*args, **kwargs):
            return method(*args, **kwargs)

        wrapper.action_name = method.__name__
        wrapper.action_group = group
        return wrapper
    return action_decorator


class HasActionsMixin:
    @classmethod
    def list_actions(cls, group="state"):
        actions = []
        for func in cls.__dict__.values():
            if callable(func):
                if hasattr(func, "action_group") and getattr(func, "action_group") == group:
                    if hasattr(func, "action_name"):
                        actions.append(getattr(func, "action_name"))
        return actions


class User(AbstractUser):
    WAITER = "waiter"
    MANAGER = "manager"
    DIRECTOR = "director"

    is_waiter = models.BooleanField(default=False)
    is_manager = models.BooleanField(default=False)
    is_director = models.BooleanField(default=False)
    current_till = models.ForeignKey("Till", null=True, on_delete=models.SET_NULL)
    current_temp_tab = models.OneToOneField("Tab", null=True, on_delete=models.SET_NULL, related_name="temp_tab_owner")
    mobile_phone = PhoneNumberField()
    online_counter = models.IntegerField(validators=[MinValueValidator(0)], default=0)

    @property
    def requires_director_to_toggle(self):
        return self.is_manager or self.is_director

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}"

    def can_grant(self, target, role):
        return (self.username != target.username or role not in ("director", "active")) and \
               (self.is_director or (self.is_manager and role in ("waiter", "active"))) and \
               (role != "active" or (self.is_director or (self.is_manager and not target.is_director)))

    def can_change_password(self, target):
        return self.can_grant(target,
                              User.DIRECTOR if target.is_director else User.MANAGER if target.is_manager else User.WAITER)

    def __str__(self):
        return f"{self.name} ({self.username})"


class UnitGroup(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=256, null=False)
    symbol = models.CharField(max_length=16, null=False)

    @property
    def units(self):
        return self.unit_set.all()

    def __str__(self):
        return self.name


class Unit(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    group = models.ForeignKey(UnitGroup, on_delete=models.CASCADE)
    name = models.CharField(max_length=256, null=False)
    symbol = models.CharField(max_length=16, null=False)
    ratio = models.FloatField()

    def __str__(self):
        return f"{self.name} ({self.group})"


class Item(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=1024, null=False)
    unitGroup = models.ForeignKey(UnitGroup, on_delete=models.PROTECT)
    allows_fractions = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=1024, null=False)
    price = models.DecimalField(max_digits=15, decimal_places=3)
    items = models.ManyToManyField(Item, through="ItemInProduct")
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class ItemInProduct(models.Model):
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    amount = models.FloatField()

    class Meta:
        verbose_name_plural = "Items in products"

    def clean(self):
        if self.amount < 0:
            raise ValidationError({"amount": "Amount can't be less than zero"})
        if self.item.allows_fractions or self.amount.is_integer():
            super(ItemInProduct, self).clean()
        else:
            raise ValidationError({"amount": "Item does not allow fractions"})

    def __str__(self):
        return f"{self.item} in {self.product}"


class Tab(models.Model):
    OPEN = 'O'
    PAID = 'P'
    ORDER_STATES = [
        (OPEN, "Open"),
        (PAID, "Paid"),
    ]
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=256, null=False)
    products = models.ManyToManyField(Product, through="ProductInTab")
    state = models.CharField(max_length=1, choices=ORDER_STATES, default=OPEN)
    openedAt = models.DateTimeField(editable=False, auto_now_add=True)
    closedAt = models.DateTimeField(null=True, blank=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, null=True)

    class Meta:
        permissions = [
            ("order_product", "Can order a product")
        ]

    def __str__(self):
        return self.name

    @property
    def total(self):
        sum = 0
        for product in ProductInTab.objects.filter(tab=self):
            sum += product.price
        return sum

    @property
    def paid(self):
        sum = 0
        for payment in self.payments.all():
            sum += payment.converted_value
        return sum

    @property
    def variance(self):
        return round(float(self.total) - self.paid, 3)

    @property
    def transfer_request_exists(self):
        return self.tabtransferrequest_set.count() > 0

    @property
    def is_temp(self):
        return self.temp_tab_owner

    def order_product(self, product, count, note, state):
        for i in range(count):
            new = ProductInTab()
            new.product = product
            new.tab = self
            new.price = product.price
            new.note = note
            new.state = state

            time = datetime.now()

            if state == ProductInTab.SERVED:
                new.preparingAt = time
                new.preparedAt = time
                new.servedAt = time
            elif state == ProductInTab.TO_SERVE:
                new.preparingAt = time
                new.preparedAt = time
            elif state == ProductInTab.PREPARING:
                new.preparingAt = time

            new.clean()
            new.save()

    def mark_paid(self, by: User):
        if hasattr(self, 'temp_tab_owner'):
            owner = self.temp_tab_owner
            owner.current_temp_tab = None
            owner.clean()
            owner.save()
            self.refresh_from_db()
        variance = self.variance
        change_payment = None
        if variance < 0:
            change_payment = PaymentInTab()
            change_payment.tab = self
            change_payment.method = TillMoneyCount.objects.get(till=by.current_till,
                                                               paymentMethod=by.current_till.changeMethod)
            change_payment.amount = variance
            change_payment.clean()
            change_payment.save()
        self.state = self.PAID
        self.closedAt = datetime.now()
        self.clean()
        self.save()
        return change_payment

    def clean(self):
        if self.state == self.PAID and hasattr(self, 'temp_tab_owner'):
            raise ValidationError("Tab cannot be saved as paid and have a temp tab owner")


class ProductInTab(models.Model):
    ORDERED = 'O'
    PREPARING = 'P'
    TO_SERVE = 'T'
    SERVED = 'S'
    VOIDED = 'V'
    SERVING_STATES = [
        (ORDERED, "Ordered"),
        (PREPARING, "Being prepared"),
        (TO_SERVE, "To be served"),
        (SERVED, "Served"),
        (VOIDED, "Voided"),
    ]
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    tab = models.ForeignKey(Tab, on_delete=models.CASCADE)
    state = models.CharField(max_length=1, choices=SERVING_STATES, default=ORDERED)
    _price = models.DecimalField(max_digits=15, decimal_places=3, db_column="price")
    orderedAt = models.DateTimeField(editable=False, default=datetime.now)
    preparingAt = models.DateTimeField(null=True, blank=True)
    preparedAt = models.DateTimeField(null=True, blank=True)
    servedAt = models.DateTimeField(null=True, blank=True)
    voidedAt = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Products in tabs"

    @property
    def price(self):
        return self._price if self.count_price else 0

    @price.setter
    def price(self, value):
        self._price = value

    def bump(self):
        if self.state == ProductInTab.ORDERED:
            self.state = ProductInTab.PREPARING
            self.preparingAt = datetime.utcnow()
        elif self.state == ProductInTab.PREPARING:
            self.state = ProductInTab.TO_SERVE
            self.preparedAt = datetime.utcnow()
        elif self.state == ProductInTab.TO_SERVE:
            self.state = ProductInTab.SERVED
            self.servedAt = datetime.utcnow()
        else:
            return False
        self.clean()
        self.save()
        return True

    @property
    def color(self):
        if self.state == ProductInTab.ORDERED:
            return "warning"
        if self.state == ProductInTab.PREPARING:
            return "secondary"
        if self.state == ProductInTab.TO_SERVE:
            return "info"
        if self.state == ProductInTab.SERVED:
            return "success"
        if self.state == ProductInTab.VOIDED:
            return "danger"

    @property
    def count_price(self):
        return self.state not in [ProductInTab.VOIDED, ]

    def void(self):
        if self.state != ProductInTab.VOIDED:
            self.state = ProductInTab.VOIDED
            self.voidedAt = datetime.utcnow()
            self.clean()
            self.save()

    def clean(self):
        def raise_over(state):
            raise ValidationError(f"Some timestamps are set when the state ({state}) does not allow it")

        def raise_under(state):
            raise ValidationError(f"The order is missing some timestamps required at its state ({state})")

        if self.state == ProductInTab.ORDERED:
            if self.preparingAt or self.preparedAt or self.servedAt or self.voidedAt:
                raise_over(self.state)
            if not self.orderedAt:
                raise_under(self.state)
        if self.state == ProductInTab.PREPARING:
            if self.preparedAt or self.servedAt or self.voidedAt:
                raise_over(self.state)
            if not self.orderedAt or not self.preparingAt:
                raise_under(self.state)
        if self.state == ProductInTab.TO_SERVE:
            if self.servedAt or self.voidedAt:
                raise_over(self.state)
            if not self.orderedAt or not self.preparingAt or not self.preparedAt:
                raise_under(self.state)
        if self.state == ProductInTab.SERVED:
            if self.voidedAt:
                raise_over(self.state)
            if not self.orderedAt or not self.preparingAt or not self.preparedAt or not self.servedAt:
                raise_under(self.state)
        if self.state == ProductInTab.VOIDED:
            if not self.voidedAt:
                raise_under(self.state)

    def void_request_exists(self, instance=None):
        requests = self.ordervoidrequest_set.filter(resolution__isnull=True)
        if instance:
            requests = requests.exclude(id=instance.id)
        return bool(requests.count())

    def __str__(self):
        return f"{self.product} in {self.tab}"


class Currency(models.Model):
    name = models.CharField(max_length=1024, null=False)
    code = models.CharField(max_length=3, null=True)
    symbol = models.CharField(max_length=8, null=True)
    countries = CountryField(multiple=True)
    subunit = models.CharField(max_length=1024, null=False)
    ratio = models.FloatField(default=1)
    enabled = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Currencies"

    def __str__(self):
        return self.name


class PaymentMethod(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=1024, null=False)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, limit_choices_to={"enabled": True})
    changeAllowed = models.BooleanField(default=False)
    _enabled = models.BooleanField(default=False, db_column='enabled')

    @property
    def enabled(self):
        return self._enabled and self.currency.enabled

    @property
    def enabled_own(self):
        return self._enabled

    @enabled_own.setter
    def enabled_own(self, value):
        self._enabled = value

    def __str__(self):
        return self.name


class Deposit(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=1024, null=False)
    methods = models.ManyToManyField(PaymentMethod, related_name="paymentOptions")
    changeMethod = models.ForeignKey(PaymentMethod, related_name="optionsAsChange", on_delete=models.PROTECT,
                                     limit_choices_to={"currency__enabled": True, "changeAllowed": True})
    depositAmount = models.DecimalField(max_digits=15, decimal_places=3, validators=[MinValueValidator(0)])
    enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Till payment options"

    def create_till(self):
        if self.enabled:
            till = Till()
            till.changeMethod = self.changeMethod
            till.depositAmount = self.depositAmount
            till.deposit = self.name
            till.clean()
            till.save()
            for method in self.methods.all():
                count = TillMoneyCount()
                count.till = till
                count.paymentMethod = method
                count.clean()
                count.save()
            return till
        else:
            return None

    @property
    def method_names(self):
        if self.methods:
            namelist = [method.name for method in self.methods.all()]
            names = namelist[0]
            if len(namelist) > 1:
                for name in namelist[1:-1]:
                    names += f", {name}"
                names += f" and {namelist[-1]}"
            return names
        else:
            return "No payment method is assigned."

    def __str__(self):
        return self.name


class Till(models.Model):
    OPEN = 'O'
    STOPPED = 'S'
    COUNTED = 'C'
    TILL_STATES = [
        (OPEN, "Open"),
        (STOPPED, "Stopped"),
        (COUNTED, "Counted"),
    ]
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    cashiers = models.ManyToManyField(User, related_name="tills_owned", limit_choices_to={"is_waiter": True})
    openedAt = models.DateTimeField(editable=False, auto_now_add=True)
    stoppedAt = models.DateTimeField(null=True, blank=True)
    countedAt = models.DateTimeField(null=True, blank=True)
    countedBy = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tills_counted",
                                  limit_choices_to={"is_manager": True}, null=True)
    state = models.CharField(max_length=1, choices=TILL_STATES, default=OPEN)
    paymentMethods = models.ManyToManyField(PaymentMethod, through="TillMoneyCount", related_name="tillsEnabled")
    changeMethod = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="tillsAsChange")
    depositAmount = models.DecimalField(max_digits=15, decimal_places=3)
    deposit = models.CharField(max_length=1024)

    @property
    def cashier_names(self):
        if self.cashiers:
            namelist = [cashier.name for cashier in self.cashiers.all()]
            names = namelist[0]
            if len(namelist) > 1:
                for name in namelist[1:-1]:
                    names += f", {name}"
                names += f" and {namelist[-1]}"
            return names
        else:
            return "Nobody is assigned"

    def stop(self):
        if self.state == Till.OPEN:
            self.state = Till.STOPPED
            self.stoppedAt = datetime.now()
            self.clean()
            self.save()
            for cashier in self.cashiers.all():
                cashier.current_till = None
                cashier.clean()
                cashier.save()
            return True
        else:
            return False

    def close(self, request):
        if self.state == Till.STOPPED:
            self.state = Till.COUNTED
            self.countedAt = datetime.now()
            self.countedBy = request.user
            self.clean()
            self.save()
            return True
        else:
            return False

    def __str__(self):
        return f"Till of cashier(s) {self.cashier_names}"


class TillMoneyCount(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    paymentMethod = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT)
    till = models.ForeignKey(Till, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=15, decimal_places=3, default=0)

    @property
    def expected(self):
        val = 0
        payments = self.paymentintab_set.all()
        for payment in payments:
            val += payment.amount
        return val

    @property
    def counted(self):
        counted = self.amount
        for edit in self.tilledit_set.all():
            counted += edit.amount
        return counted

    def add_edit(self, amount, reason):
        counted = self.counted
        if -1 * amount > counted:
            amount = -1 * counted
        if amount == 0:
            return None
        edit = TillEdit()
        edit.count = self
        edit.amount = amount
        edit.reason = reason
        edit.clean()
        edit.save()
        return edit

    def __str__(self):
        return f"Money count of {self.paymentMethod.currency.code} {self.amount} via {self.paymentMethod} in till {self.till}"


class TillEdit(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    count = models.ForeignKey(TillMoneyCount, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=15, decimal_places=3, default=0)
    created = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()


class PaymentInTab(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    tab = models.ForeignKey(Tab, on_delete=models.CASCADE, related_name="payments")
    method = models.ForeignKey(TillMoneyCount, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=15, decimal_places=3)

    @property
    def converted_value(self):
        return round(float(self.amount) * self.method.paymentMethod.currency.ratio, 3)

    def clean(self):
        super(PaymentInTab, self).clean()

        if not self.method.paymentMethod.enabled:
            raise ValidationError(f"You can't create payments with payment method {self.method.paymentMethod.name}, "
                                  f"it is currently disabled.")


class OrderVoidRequest(models.Model):
    APPROVED = 'A'
    REJECTED = 'R'
    RESOLUTIONS = [
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    order = models.ForeignKey(ProductInTab, on_delete=models.CASCADE)
    waiter = models.ForeignKey(User, on_delete=models.PROTECT, related_name='voids_requested')
    manager = models.ForeignKey(User, on_delete=models.PROTECT, related_name='voids_approved', null=True)
    requestedAt = models.DateTimeField(auto_now_add=True, editable=False)
    resolvedAt = models.DateTimeField(null=True)
    resolution = models.CharField(max_length=1, choices=RESOLUTIONS, blank=True, null=True)

    def approve(self, manager):
        if not self.resolution:
            self.resolution = OrderVoidRequest.APPROVED
            self.manager = manager
            self.resolvedAt = datetime.now()
            self.clean()
            self.save()
            self.order.void()
            self.notify_waiter()
            return True
        else:
            return False

    def reject(self, manager):
        if not self.resolution:
            self.resolution = OrderVoidRequest.REJECTED
            self.manager = manager
            self.resolvedAt = datetime.now()
            self.clean()
            self.save()
            self.notify_waiter()
            return True
        else:
            return False

    def notify_waiter(self):
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"notifications_user-{self.waiter.id}",
            {
                "type": "notification.void_request_resolved",
                "void_request": {
                    "notification_type": "void_request_resolved",
                    "request_id": str(self.id),
                    "manager": {
                        "first_name": self.manager.first_name,
                        "last_name": self.manager.last_name,
                        "username": self.manager.username,
                    },
                    "order": {
                        "id": str(self.order.id),
                        "product_name": self.order.product.name,
                        "state": self.order.state,
                        "ordered_at": str(self.order.orderedAt),
                        "preparing_at": str(self.order.preparingAt),
                        "prepared_at": str(self.order.preparedAt),
                        "served_at": str(self.order.servedAt),
                        "note": self.order.note,
                        "tab_name": self.order.tab.name,
                        "tab_id": str(self.order.tab.id),
                        "review_url": reverse("waiter/direct/order") if hasattr(self.order.tab, "temp_tab_owner") else
                        reverse("waiter/tabs/tab", kwargs={"id": self.order.tab.id}),
                    },
                    "resolution": self.resolution,
                },
            },
        )

    def clean(self):
        super(OrderVoidRequest, self).clean()

        if self.order.void_request_exists(self):
            raise ValidationError("It appears there already is another unresolved request associated with this order.")
        if self.order.state == ProductInTab.VOIDED:
            raise ValidationError("The order is already voided.")

        if bool(self.resolution) != bool(self.resolvedAt):
            raise ValidationError("Resolution and resolution timestamp must either be both set or both None.")


class TabTransferRequest(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    tab = models.ForeignKey(Tab, on_delete=models.CASCADE)
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tab_transfers_requested")
    new_owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="tab_transfers_gaining")
    requestedAt = models.DateTimeField(auto_now_add=True, editable=False)

    def approve(self, manager):
        old_owner = self.tab.owner
        self.tab.owner = self.new_owner
        self.tab.clean()
        self.tab.save()
        self.notify_waiter(manager, old_owner)
        self.delete()

    def reject(self, manager):
        self.notify_waiter(manager)
        self.delete()

    def notify_waiter(self, manager, old_owner=False):
        is_claim = self.requester == self.new_owner
        channel_layer = get_channel_layer()
        if old_owner != False:
            if is_claim:
                message_old = f"{self.requester}'s claim request on tab {self.tab.name} was approved by {manager.name}."
                message_new = f"Your claim request on tab {self.tab.name} was approved by {manager.name}."
            else:
                message_old = f"Your request to transfer tab {self.tab.name} to {self.new_owner.name} was approved by " \
                              f"{manager.name}."
                message_new = f"{self.requester}'s request to transfer tab {self.tab.name} to you was approved by " \
                              f"{manager.name}"

            if old_owner:
                async_to_sync(channel_layer.group_send)(
                    f"notifications_user-{old_owner.id}",
                    {
                        "type": "notification.tab_transfer_request_resolved",
                        "message": message_old,
                        "resolution": True,
                    },
                )
            async_to_sync(channel_layer.group_send)(
                f"notifications_user-{self.new_owner.id}",
                {
                    "type": "notification.tab_transfer_request_resolved",
                    "message": message_new,
                    "resolution": True,
                },
            )
        else:
            if is_claim:
                message = f"Your claim request on tab {self.tab.name} was rejected by {manager.name}."
            else:
                message = f"Your request to transfer tab {self.tab.name} to {self.new_owner.name} was rejected by" \
                          f"{manager.name}."

            async_to_sync(channel_layer.group_send)(
                f"notifications_user-{self.requester.id}",
                {
                    "type": "notification.tab_transfer_request_resolved",
                    "message": message,
                    "resolution": False,
                },
            )

    @property
    def is_transfer(self):
        return self.tab.owner == self.requester and self.requester != self.new_owner

    @property
    def is_claim(self):
        return self.tab.owner != self.requester and self.requester == self.new_owner

    def clean(self):
        super(TabTransferRequest, self).clean()

        if self.tab.transfer_request_exists:
            raise ValidationError("It appears there already is another unresolved request associated with this tab.")
        if not (self.is_transfer or self.is_claim):
            raise ValidationError("The user references don't conform to a valid pattern.")
        if not self.new_owner.is_waiter:
            raise ValidationError("The requested new owner is not a waiter. "
                                  "Grant him waiter role or select another new owner.")

    @property
    def type(self):
        if self.is_transfer:
            return "Transfer"
        elif self.is_claim:
            return "Claim"
        else:
            return "Nonsense"


def generate_expense_upload_to_filename(instance, filename):
    return f"posapp/expenses/{instance.id}/{filename}"


class Expense(HasActionsMixin, ConcurrentTransitionMixin, models.Model):
    NEW = "new"
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    APPEALED = "appealed"
    PAID = "paid"
    STATES = [
        (NEW, "New"),
        (REQUESTED, "Requested"),
        (ACCEPTED, "Accepted"),
        (REJECTED, "Rejected"),
        (APPEALED, "Appealed"),
        (PAID, "Paid"),
    ]
    STATE_COLORS = {
        NEW: "secondary",
        REQUESTED: "primary",
        ACCEPTED: "success",
        REJECTED: "danger",
        APPEALED: "warning",
        PAID: "info",
    }
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    amount = models.DecimalField(max_digits=15, decimal_places=3, validators=[MinValueValidator(0)])
    requested_at = models.DateTimeField(auto_now_add=True)
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="expenses_requested")
    description = models.TextField()
    invoice_file = models.FileField(upload_to=generate_expense_upload_to_filename, null=True, blank=True)
    state = FSMField(default='new', choices=STATES, protected=True)

    @fsm_log_by
    @transition(field=state, source=[NEW, APPEALED], target=REQUESTED,
                permission=lambda instance, user: instance.requested_by == user,
                conditions=[lambda instance: instance.invoice_file])
    @action()
    def submit(self, by, description):
        pass

    @fsm_log_by
    @transition(field=state, source=[REQUESTED], target=ACCEPTED,
                permission=lambda instance, user: user.is_director)
    @action()
    def accept(self, by, description):
        pass

    @fsm_log_by
    @fsm_log_description
    @transition(field=state, source=[REQUESTED], target=REJECTED,
                permission=lambda instance, user: user.is_director)
    @action()
    def reject(self, by, description):
        pass

    @fsm_log_by
    @fsm_log_description
    @transition(field=state, source=REJECTED, target=APPEALED,
                permission=lambda instance, user: instance.requested_by == user or user.is_director)
    @action()
    def appeal(self, by, description):
        pass

    @fsm_log_by
    @transition(field=state, source=ACCEPTED, target=PAID, permission=lambda instance, user: user.is_director)
    @action()
    def pay(self, by, description):
        pass

    @property
    def state_color(self):
        return self.STATE_COLORS[self.state]

    @property
    def is_editable(self):
        return self.state in [Expense.NEW, Expense.APPEALED]

    @property
    def invoice_file_type(self):
        if not self.invoice_file:
            return "empty"
        guess, _ = mimetypes.guess_type(self.invoice_file.name)
        return "image/*" if re.compile(r'^image/.*$').match(guess) else guess

    def clean(self):
        super(Expense, self).clean()
        if not self.invoice_file and self.state != "new":
            raise ValidationError("Invoice field may only be empty if the state is new.")

    def set_transition_permissions(self, user):
        self.can_submit = has_transition_perm(self.submit, user)
        self.can_accept = has_transition_perm(self.accept, user)
        self.can_reject = has_transition_perm(self.reject, user)
        self.can_appeal = has_transition_perm(self.appeal, user)
        self.can_pay = has_transition_perm(self.pay, user)
        self.can_edit = self.requested_by == user and self.is_editable
        self.button_comment = "Edit" if self.can_edit else "Review"


@receiver(models.signals.post_delete, sender=Expense)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    if instance.invoice_file:
        if os.path.isfile(instance.invoice_file.path):
            os.remove(instance.invoice_file.path)


@receiver(models.signals.pre_save, sender=Expense)
def auto_delete_file_on_change(sender, instance, **kwargs):
    if not instance.pk:
        return False

    try:
        old_file = Expense.objects.get(pk=instance.pk).invoice_file
    except Expense.DoesNotExist:
        return False

    if old_file:
        new_file = instance.invoice_file
        if not old_file == new_file:
            if os.path.isfile(old_file.path):
                os.remove(old_file.path)
