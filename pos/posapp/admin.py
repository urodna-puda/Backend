from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm

from posapp.models import *


# Register your models here.
class UserChangeForm(BaseUserChangeForm):
    class Meta(BaseUserChangeForm.Meta):
        model = User


class UserAdmin(BaseUserAdmin):
    form = UserChangeForm

    fieldsets = BaseUserAdmin.fieldsets + (
        ("POS Abilities", {'fields': ('is_waiter', 'is_manager')}),
    )


class ProductItemInline(admin.TabularInline):
    verbose_name = "item in product"
    verbose_name_plural = "items in product"
    model = ItemInProduct
    extra = 2


class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'price']
    search_fields = ['name']
    list_filter = ['price']
    ordering = ['name']
    inlines = [ProductItemInline]


class UnitGroupUnitInline(admin.TabularInline):
    model = Unit
    extra = 2


class UnitGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'symbol']
    search_fields = ['name', 'symbol']
    ordering = ['name']
    inlines = [UnitGroupUnitInline]


class UnitAdmin(admin.ModelAdmin):
    list_display = ['name', 'symbol', 'group', 'ratio']
    search_fields = ['name', 'symbol']
    list_filter = ['group']
    ordering = ['group', 'name']


class ItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'unitGroup']
    search_fields = ['name']
    list_filter = ['unitGroup']
    ordering = ['name']


class ItemInProductAdmin(admin.ModelAdmin):
    list_display = ['item', 'product', 'amount']
    list_filter = ['item', 'product', 'amount']
    ordering = ['product', 'item']


class TabProductInline(admin.TabularInline):
    verbose_name = "Product in tab"
    verbose_name_plural = "Products in tab"
    model = ProductInTab
    extra = 2


class TabAdmin(admin.ModelAdmin):
    list_display = ['name', 'state', 'openedAt', 'closedAt', 'total']
    search_fields = ['name']
    list_filter = ['state', 'openedAt', 'closedAt']
    ordering = ['openedAt', 'closedAt']
    inlines = [TabProductInline]


class ProductInTabAdmin(admin.ModelAdmin):
    list_display = ['product', 'tab', 'state', 'price']
    list_filter = ['product', 'tab', 'state', 'price']
    ordering = ['tab', 'state']


class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['pk', 'enabled', 'code', 'name', 'symbol', 'subunit']
    search_fields = ['pk', 'code', 'name', 'symbol', 'subunit']
    list_filter = ['enabled', 'countries']
    ordering = ['code']
    actions = ['enable_currency', 'disable_currency']

    def enable_currency(self, request, queryset):
        queryset.update(enabled=True)

    enable_currency.short_description = 'Enable'

    def disable_currency(self, request, queryset):
        queryset.update(enabled=False)

    disable_currency.short_description = 'Disable'


class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['name', 'currency']
    search_fields = ['name']
    list_filter = ['currency']
    ordering = ['name']


class OrderPaymentInline(admin.TabularInline):
    verbose_name = "Payment in order"
    verbose_name_plural = "Payments in order"
    model = PaymentInOrder
    extra = 2


class OrderAdmin(admin.ModelAdmin):
    list_display = ['tab', 'state']
    search_fields = ['tab']
    list_filter = ['state']
    ordering = ['createdAt']
    inlines = [OrderPaymentInline]


class PaymentInOrderAdmin(admin.ModelAdmin):
    list_display = ['order', 'method', 'amount']
    search_fields = ['order']
    list_filter = ['method']
    ordering = ['order', 'method', 'amount']


admin.site.register(User, UserAdmin)
admin.site.register(Product, ProductAdmin)
admin.site.register(UnitGroup, UnitGroupAdmin)
admin.site.register(Unit, UnitAdmin)
admin.site.register(Item, ItemAdmin)
# admin.site.register(ItemInProduct, ItemInProductAdmin)
admin.site.register(Tab, TabAdmin)
# admin.site.register(ProductInTab, ProductInTabAdmin)
admin.site.register(Currency, CurrencyAdmin)
admin.site.register(PaymentMethod, PaymentMethodAdmin)
admin.site.register(Order, OrderAdmin)
# admin.site.register(PaymentInOrder, PaymentInOrderAdmin)
