from datetime import datetime
from uuid import uuid4

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField


# Create your models here.

class User(AbstractUser):
    WAITER = "waiter"
    MANAGER = "manager"
    ADMIN = "admin"

    is_waiter = models.BooleanField(default=False)
    is_manager = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    current_till = models.ForeignKey("Till", null=True, on_delete=models.SET_NULL)
    current_temp_tab = models.ForeignKey("Tab", null=True, on_delete=models.SET_NULL)
    mobile_phone = PhoneNumberField()

    @property
    def requires_admin_to_toggle(self):
        return self.is_manager or self.is_admin

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}"

    def can_grant(self, target, role):
        return (self.username != target.username or role not in ("admin", "active")) and \
               (self.is_admin or (self.is_manager and role in ("waiter", "active"))) and \
               (role != "active" or (self.is_admin or (self.is_manager and not target.is_admin)))

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
        if self.item.allows_fractions or self.amount.is_integer():
            super(ItemInProduct, self).clean()
        else:
            raise ValidationError("Item does not allow fractions")

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

            new.save()

    def mark_paid(self, by: User):
        variance = self.variance
        change_payment = None
        if variance < 0:
            change_payment = PaymentInTab()
            change_payment.tab = self
            change_payment.method = TillMoneyCount.objects.get(till=by.current_till,
                                                               paymentMethod=by.current_till.changeMethod)
            change_payment.amount = variance
            change_payment.save()
        self.state = self.PAID
        self.closedAt = datetime.now()
        self.save()
        return change_payment


class ProductInTab(models.Model):
    ORDERED = 'O'
    PREPARING = 'P'
    TO_SERVE = 'T'
    SERVED = 'S'
    SERVING_STATES = [
        (ORDERED, "Ordered"),
        (PREPARING, "Being prepared"),
        (TO_SERVE, "To be served"),
        (SERVED, "Served"),
    ]
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    tab = models.ForeignKey(Tab, on_delete=models.CASCADE)
    state = models.CharField(max_length=1, choices=SERVING_STATES, default=ORDERED)
    price = models.DecimalField(max_digits=15, decimal_places=3)
    orderedAt = models.DateTimeField(editable=False, auto_now_add=True)
    preparingAt = models.DateTimeField(null=True, blank=True)
    preparedAt = models.DateTimeField(null=True, blank=True)
    servedAt = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Products in tabs"

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
        self.save()
        return True

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

    def __str__(self):
        return self.name


class TillPaymentOptions(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=1024, null=False)
    methods = models.ManyToManyField(PaymentMethod, related_name="paymentOptions")
    changeMethod = models.ForeignKey(PaymentMethod, related_name="optionsAsChange", on_delete=models.PROTECT,
                                     limit_choices_to={"currency__enabled": True, "changeAllowed": True})
    depositAmount = models.DecimalField(max_digits=15, decimal_places=3)
    enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Till payment options"

    def create_till(self):
        till = Till()
        till.changeMethod = self.changeMethod
        till.depositAmount = self.depositAmount
        till.save()
        for method in self.methods.all():
            count = TillMoneyCount()
            count.till = till
            count.paymentMethod = method
            count.save()
        return till

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

    @property
    def deposit(self):
        return self.changeMethod.name + " " + str(self.depositAmount)

    def stop(self):
        if self.state == Till.OPEN:
            self.state = Till.STOPPED
            self.stoppedAt = datetime.now()
            self.save()
            for cashier in self.cashiers.all():
                cashier.current_till = None
                cashier.save()
            return True
        else:
            return False

    def close(self, request):
        if self.state == Till.STOPPED:
            self.state = Till.COUNTED
            self.countedAt = datetime.now()
            self.countedBy = request.user
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
