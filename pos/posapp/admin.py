from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from phonenumber_field import formfields, widgets

from posapp.models import *


# Register your models here.
class UserChangeForm(BaseUserChangeForm):
    mobile_phone = formfields.PhoneNumberField(widget=widgets.PhoneNumberInternationalFallbackWidget)

    class Meta(BaseUserChangeForm.Meta):
        model = User


class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    list_display = BaseUserAdmin.list_display + ('is_waiter', 'is_manager', 'is_director', )
    actions = BaseUserAdmin.actions + ['make_waiter', 'make_manager', 'make_director',
                                       'strip_waiter', 'strip_manager', 'strip_director', ]

    def make_director(self, request, queryset):
        queryset.update(is_director=True)

    make_director.short_description = 'Make director'

    def make_waiter(self, request, queryset):
        queryset.update(is_waiter=True)

    make_waiter.short_description = 'Make waiter'

    def make_manager(self, request, queryset):
        queryset.update(is_manager=True)

    make_manager.short_description = 'Make manager'

    def strip_director(self, request, queryset):
        queryset.update(is_director=False)

    strip_director.short_description = 'Make not director'

    def strip_waiter(self, request, queryset):
        queryset.update(is_waiter=False)

    strip_waiter.short_description = 'Make not waiter'

    def strip_manager(self, request, queryset):
        queryset.update(is_manager=False)

    strip_manager.short_description = 'Make not manager'

    fieldsets = BaseUserAdmin.fieldsets + (
        ("POS Abilities", {'fields': ('is_waiter', 'is_manager', 'is_director',)}),
        ("Contact info", {'fields': ('mobile_phone',)})
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


class DepositAdmin(admin.ModelAdmin):
    list_display = ['name', 'changeMethod', 'depositAmount', 'enabled']
    search_fields = ['name']
    list_filter = ['changeMethod', 'depositAmount', 'enabled']
    ordering = ['name', 'depositAmount']


class TillMoneyCountsInline(admin.TabularInline):
    verbose_name = "Money count"
    verbose_name_plural = "Money counts"
    model = TillMoneyCount
    extra = 0


class TillAdmin(admin.ModelAdmin):
    readonly_fields = ['cashier_names']
    list_display = ['state', 'openedAt', 'stoppedAt', 'countedAt', 'countedBy']
    list_filter = ['state', 'countedBy']
    ordering = ['openedAt', 'stoppedAt', 'countedAt']
    inlines = [TillMoneyCountsInline]


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
admin.site.register(TillPaymentOptions, DepositAdmin)
admin.site.register(Till, TillAdmin)
# admin.site.register(PaymentInOrder, PaymentInOrderAdmin)
