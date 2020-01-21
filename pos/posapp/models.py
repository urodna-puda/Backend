from uuid import uuid4

from django.db import models
from django_countries.fields import CountryField


# Create your models here.

class Product(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=1024, null=False)
    price = models.DecimalField(max_digits=15, decimal_places=3)

    def __str__(self):
        return self.name


class UnitGroup(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=256, null=False)
    symbol = models.CharField(max_length=16, null=False)

    def __str__(self):
        return self.name


class Unit(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    group = models.ForeignKey(UnitGroup, on_delete=models.PROTECT)
    name = models.CharField(max_length=256, null=False)
    symbol = models.CharField(max_length=16, null=False)
    ratio = models.FloatField()

    def __str__(self):
        return f"{self.name} ({self.group})"


class Item(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=1024, null=False)
    unitGroup = models.ForeignKey(UnitGroup, on_delete=models.PROTECT)

    def __str__(self):
        return self.name


class ItemInProduct(models.Model):
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    amount = models.FloatField()

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
    openedAt = models.DateTimeField(auto_now_add=True)
    closedAt = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def total(self):
        sum = 0
        for product in ProductInTab.objects.filter(tab=self):
            sum += product.price
        return sum


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
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    tab = models.ForeignKey(Tab, on_delete=models.CASCADE)
    state = models.CharField(max_length=1, choices=SERVING_STATES, default=ORDERED)
    price = models.DecimalField(max_digits=15, decimal_places=3)
    orderedAt = models.DateTimeField(auto_now_add=True)
    preparingAt = models.DateTimeField(null=True, blank=True)
    preparedAt = models.DateTimeField(null=True, blank=True)
    servedAt = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True)

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

    def __str__(self):
        return self.name


class PaymentMethod(models.Model):
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    name = models.CharField(max_length=1024, null=False)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, limit_choices_to={"enabled": True})

    def __str__(self):
        return self.name


class Order(models.Model):
    CREATED = 'C'
    PAID = 'P'
    ORDER_STATES = [
        (CREATED, "Created"),
        (PAID, "Paid"),
    ]
    id = models.UUIDField(primary_key=True, null=False, editable=False, default=uuid4)
    tab = models.OneToOneField(Tab, on_delete=models.PROTECT, related_name="order")
    state = models.CharField(max_length=1, choices=ORDER_STATES, default=CREATED)
    createdAt = models.DateTimeField(auto_now_add=True)
    payments = models.ManyToManyField(PaymentMethod, through="PaymentInOrder")

    def __str__(self):
        return f"Order of tab {self.tab}"


class PaymentInOrder(models.Model):
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT)
    order = models.ForeignKey(Order, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=15, decimal_places=3)

    def __str__(self):
        return f"Payment of {self.method.currency.symbol}{self.amount} via {self.method} for {self.order}"
