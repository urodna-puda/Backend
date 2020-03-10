import decimal
import uuid

# Create your views here.
from django import views
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, ProtectedError
from django.shortcuts import render as render_django, redirect

from posapp.forms import CreateUserForm, CreatePaymentMethodForm, CreateEditProductForm, ItemsInProductFormSet
from posapp.models import Tab, ProductInTab, Product, User, Currency, Till, TillPaymentOptions, TillMoneyCount, \
    PaymentInTab, PaymentMethod, UnitGroup, Unit, ItemInProduct, Item
from posapp.security import waiter_login_required, manager_login_required, admin_login_required


def render(request, template_name, context, content_type=None, status=None, using=None):
    return render_django(request, template_name, dict(context), content_type, status, using)


class Context:
    def __init__(self, request):
        self.page = request.get_full_path()[1:]
        self.waiter_role = request.user.is_waiter
        self.manager_role = request.user.is_manager
        self.admin_role = request.user.is_admin
        self.notifications = []
        self.data = {}

    def add_pagination_context(self, manager, page, page_length, key):
        count = manager.count()
        last_page = count // page_length
        self.data[key] = {}

        self.data[key]['data'] = manager[page * page_length:(page + 1) * page_length]

        self.data[key]['showing'] = {}
        self.data[key]['showing']['from'] = page * page_length
        self.data[key]['showing']['to'] = min((page + 1) * page_length - 1, count - 1)
        self.data[key]['showing']['of'] = count

        self.data[key]['pages'] = {}
        self.data[key]['pages']['previous'] = page - 1
        self.data[key]['pages']['showPrevious'] = self.data[key]['pages']['previous'] >= 0
        self.data[key]['pages']['next'] = page + 1
        self.data[key]['pages']['showNext'] = self.data[key]['pages']['next'] <= last_page
        self.data[key]['pages']['last'] = last_page

        links = []
        if page < (last_page / 2):
            first_link = max(0, page - 2)
            start = first_link
            end = min(last_page + 1, first_link + 5)
        else:
            last_link = min(last_page, page + 2) + 1
            start = max(0, last_link - 5)
            end = last_link

        for i in range(start, end):
            links.append({'page': i, 'active': i == page})

        self.data[key]['pages']['links'] = links

    def __getitem__(self, item):
        return self.data[item]

    def __setitem__(self, key, value):
        self.data[key] = value

    def __len__(self):
        return 5 + len(self.data)

    def __contains__(self, item):
        return item in self.data

    def __iter__(self):
        yield 'page', self.page
        yield 'waiter_role', self.waiter_role
        yield 'manager_role', self.manager_role
        yield 'admin_role', self.manager_role
        yield 'notifications', self.notifications
        for key in self.data:
            yield key, self.data[key]


def generate_page_length_options(page_length):
    options = {
        "len5": False,
        "len10": False,
        "len20": False,
        "len50": False,
        "len100": False,
        "len200": False,
        "len500": False,
        "other": False,
        "value": page_length,
    }
    if "len" + str(page_length) in options:
        options["len" + str(page_length)] = True
    else:
        options["other"] = True
    return options


@login_required
def index(request):
    return redirect("waiter/tabs")


def prepare_tab_dict(tab):
    variance = tab.variance
    out = {
        'name': tab.name,
        'id': tab.id,
        'total': tab.total,
        'paid': tab.paid,
        'variance': abs(variance),
        'showVariance': variance != 0,
        'varianceLabel': 'To pay' if variance > 0 else 'To change',
        'showFinaliseAuto': variance == 0,
        'showFinaliseChange': variance < 0,
        'products': []
    }

    products_list = ProductInTab.objects.filter(tab=tab)
    products = {}
    for product in products_list:
        if product.product.id not in products:
            products[product.product.id] = {
                'id': product.product.id,
                'name': product.product.name,
                'variants': {},
            }

        if product.note not in products[product.product.id]['variants']:
            products[product.product.id]['variants'][product.note] = {
                'note': product.note,
                'orderedCount': 0,
                'preparingCount': 0,
                'toServeCount': 0,
                'servedCount': 0,
                'showOrdered': False,
                'showPreparing': False,
                'showToServe': False,
                'showServed': False,
                'total': 0,
            }

        if product.state == ProductInTab.ORDERED:
            products[product.product.id]['variants'][product.note]['orderedCount'] += 1
            products[product.product.id]['variants'][product.note]['showOrdered'] = True
        elif product.state == ProductInTab.PREPARING:
            products[product.product.id]['variants'][product.note]['preparingCount'] += 1
            products[product.product.id]['variants'][product.note]['showPreparing'] = True
        elif product.state == ProductInTab.TO_SERVE:
            products[product.product.id]['variants'][product.note]['toServeCount'] += 1
            products[product.product.id]['variants'][product.note]['showToServe'] = True
        elif product.state == ProductInTab.SERVED:
            products[product.product.id]['variants'][product.note]['servedCount'] += 1
            products[product.product.id]['variants'][product.note]['showServed'] = True

        products[product.product.id]['variants'][product.note]['total'] += product.price

    for product in products:
        variants = []
        for variant in products[product]['variants']:
            variants.append(products[product]['variants'][variant])

        out['products'].append({
            'id': products[product]['id'],
            'name': products[product]['name'],
            'variants': variants,
        })

    return out


@waiter_login_required
def waiter_tabs(request):
    context = Context(request)
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
    return render(request, template_name="waiter/tabs.html", context=context)


@waiter_login_required
def waiter_tabs_tab(request):
    context = Context(request)
    if request.method == "POST":
        if "id" in request.POST:
            id = uuid.UUID(request.POST["id"])
            context["id"] = id
            current_till = request.user.current_till
            if current_till:
                context["money_counts"] = current_till.tillmoneycount_set.all()
                try:
                    tab = Tab.objects.get(id=id)
                    context["tab_open"] = tab.state == Tab.OPEN
                    if context["tab_open"]:
                        if check_dict(request.POST, ["moneyCountId", "amount"]):
                            try:
                                money_count_id = uuid.UUID(request.POST["moneyCountId"])
                                context["last_used_method"] = money_count_id
                                amount = decimal.Decimal(request.POST["amount"])
                                if amount < 0:
                                    messages.warning(request, "Payment amount must be greater than zero.")
                                else:
                                    money_count = request.user.current_till.tillmoneycount_set.get(id=money_count_id)
                                    payment = PaymentInTab()
                                    payment.tab = tab
                                    payment.method = money_count
                                    payment.amount = amount
                                    payment.save()
                                    messages.success(request, "Payment created successfully")
                            except TillMoneyCount.DoesNotExist:
                                messages.warning(request, "Invalid request: Payment method does not exist")
                        if check_dict(request.POST, ["paymentId", "delete"]):
                            try:
                                payment_id = uuid.UUID(request.POST["paymentId"])
                                payment = PaymentInTab.objects.get(id=payment_id, tab=tab)
                                payment.delete()
                                messages.success(request, "Payment was deleted successfully")
                            except PaymentInTab.DoesNotExist:
                                messages.warning(request,
                                                 "The specified payment can't be deleted as it does not exist.")
                        if check_dict(request.POST, ["close"]):
                            change_payment = tab.mark_paid(request.user)
                            messages.success(request, "The Tab was marked as paid.")
                            if change_payment:
                                messages.info(request, f"The remaining variance of {change_payment.amount} was "
                                                       f"returned via {change_payment.method.paymentMethod.name}")
                    context["tab"] = prepare_tab_dict(tab)
                    context["payments"] = tab.payments.all()
                    context["change_method_name"] = current_till.changeMethod.name
                except Tab.DoesNotExist:
                    messages.error(request, "Invalid request: specified Tab does not exist. "
                                            "Go back to previous page and try it again.")
            else:
                messages.error(request,
                               "You don't have a till assigned. If you want to accept payment, "
                               "ask a manager to assign you a till.")
        else:
            messages.error(request, "Invalid request: Tab ID is missing. Go back to previous page and try it again.")
    else:
        messages.error(request, "Invalid request. Go back to previous page and try it again.")
    return render(request, template_name="waiter/tabs/tab.html", context=context)


@waiter_login_required
def waiter_orders(request):
    context = Context(request)
    return render(request, template_name="waiter/orders.html", context=context)


@manager_login_required
def manager_users_overview(request):
    context = Context(request)
    page_length = int(request.GET.get('page_length', 20))
    page = int(request.GET.get('page', 0))

    users = User.objects.filter(is_active=True).order_by("last_name", "first_name")
    context['me'] = request.user.username
    context.add_pagination_context(users, page, page_length, 'users')

    return render(request, template_name="manager/users/overview.html", context=context)


def check_dict(dictionary, keys):
    for key in keys:
        if key not in dictionary:
            return False
    return True


@manager_login_required
def manager_users_create(request):
    context = Context(request)
    if request.method == 'GET':
        form = CreateUserForm()
    elif request.method == 'POST':
        print(request.POST)
        user = User()
        form = CreateUserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f"The user {form.cleaned_data['username']} was created successfully")
            return redirect("manager/users/overview")
        else:
            print("form is not valid")

    else:
        # TODO Replace with proper handler
        assert False
    context['form'] = form
    return render(request, template_name="manager/users/create.html", context=context)


@manager_login_required
def manager_tills_overview(request):
    context = Context(request)
    page_length = int(request.GET.get('page_length', 20))
    page_open = int(request.GET.get('page_open', 0))
    page_stopped = int(request.GET.get('page_closed', 0))
    page_counted = int(request.GET.get('page_counted', 0))

    open_tills = Till.objects.filter(state=Till.OPEN)
    stopped_tills = Till.objects.filter(state=Till.STOPPED)
    counted_tills = Till.objects.filter(state=Till.COUNTED)
    context.add_pagination_context(open_tills, page_open, page_length, 'open')
    context.add_pagination_context(stopped_tills, page_stopped, page_length, 'stopped')
    context.add_pagination_context(counted_tills, page_counted, page_length, 'counted')

    context["page_open"] = page_open
    context["page_stopped"] = page_stopped
    context["page_counted"] = page_counted
    context["page_length"] = generate_page_length_options(page_length)

    return render(request, template_name="manager/tills/overview.html", context=context)


@manager_login_required
def manager_tills_assign(request):
    context = Context(request)
    if request.method == 'POST':
        if all(k in request.POST for k in ["users", "options"]):
            usernames = request.POST.getlist("users")
            options_id = request.POST["options"]

            try:
                options = TillPaymentOptions.objects.get(id=uuid.UUID(options_id))
                till = options.create_till()
                for username in usernames:
                    user = User.objects.get(username=username)
                    if user.current_till:
                        messages.warning(request,
                                         f"The user {user} was excluded from this Till "
                                         f"as they already have another Till assigned.")
                    else:
                        user.current_till = till
                        user.save()
                        till.cashiers.add(user)
                messages.success(request, "The till was assigned successfully")
            except User.DoesNotExist:
                messages.error(request, "One of the selected users does not exist")
            except TillPaymentOptions.DoesNotExist:
                messages.error(request, "The selected payment options config does not exist. It may have also been "
                                        "disabled by an administrator.")
        else:
            messages.error(request, "Some required fields are missing")

    context["users"] = User.objects.filter(is_waiter=True, current_till=None)
    context["options"] = TillPaymentOptions.objects.filter(enabled=True)

    return render(request, template_name="manager/tills/assign.html", context=context)


@manager_login_required
def manager_tills_till(request):
    context = Context(request)
    if request.method == "POST":
        if "id" in request.POST:
            id = uuid.UUID(request.POST["id"])
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
            return render(request, template_name="manager/tills/till.html", context=context)
    messages.error(request, 'Server error occurred, please try again.')
    return redirect("manager/tills/overview")


@manager_login_required
def manager_tills_till_stop(request):
    if request.method == "GET":
        return redirect('manager/tills/overview')
    elif request.method == "POST":
        try:
            till = Till.objects.get(id=uuid.UUID(request.POST["id"]))
            if till.state == Till.OPEN:
                if till.stop():
                    messages.success(request, 'The till was stopped successfully. It is now available for counting.')
                else:
                    messages.error(request, 'An error occured during stopping. Please try again.')
            else:
                messages.warning(request, f'The till is in a state from which it cannot be closed: {till.state}')
        except Till.DoesNotExist:
            messages.error(request, 'The specified till does not exist.')
    return redirect("manager/tills/overview")


@manager_login_required
def manager_tills_till_count(request):
    context = Context(request)
    if request.method == "GET":
        return redirect("manager/tills/overview")
    id = uuid.UUID(request.POST["id"])
    context["id"] = id
    try:
        till = Till.objects.get(id=id)
        zeroed = []
        if "save" in request.POST:
            counts = till.tillmoneycount_set.all()
            for count in counts:
                count.amount = float(request.POST[f"counted-{count.id}"])
                if count.amount < 0:
                    zeroed.append(count.id)
                    count.amount = 0
                count.save()

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
        messages.error(request, "One of the counts required was missing in the request. Please fill all counts")

    return render(request, template_name="manager/tills/till/count.html", context=context)


@manager_login_required
def manager_tills_till_close(request):
    level = messages.ERROR
    message = 'Server error occurred, please try again'
    if request.method == "POST":
        if "id" in request.POST:
            try:
                till = Till.objects.get(id=uuid.UUID(request.POST["id"]))
                if till.state == Till.STOPPED:
                    till.close(request)
                    level = messages.SUCCESS
                    message = "The till was closed successfully"
                else:
                    level = messages.WARNING
                    message = f'The till is in a state from which it cannot be closed: {till.state}'
            except Till.DoesNotExist:
                level = messages.ERROR
                message = 'The specified till does not exist.'
    messages.add_message(request, level, message)
    return redirect("manager/tills/overview")


@manager_login_required
def manager_tills_till_edit(request):
    context = Context(request)
    if request.method == "POST":
        if "id" in request.POST:
            id = uuid.UUID(request.POST["id"])
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
                            messages.info(request, f"The edit had to be changed so that total amount of money "
                                                   f"wouldn't be negative. Actual saved amount is {edit.amount} "
                                                   f"and new counted amount is {count.counted}.")
                        else:
                            messages.success(request, 'The edit was saved.')
                    except TillMoneyCount.DoesNotExist:
                        messages.warning(request,
                                         'The specified payment method does not exist in this till. Please try again.'
                                         )
                context["id"] = id
                context["counts"] = till.tillmoneycount_set.all()
            except Till.DoesNotExist:
                messages.error(request,
                               'The selected till is not available for edits. It either does not exist or '
                               'is in a state that does not allow edits.')

            return render(request, template_name="manager/tills/till/edit.html", context=context)
    messages.error(request, 'Server error occurred, please try again.')
    return redirect("manager/tills/overview")


@admin_login_required
def admin_finance_currencies(request):
    context = Context(request)
    page_length = int(request.GET.get('page_length', 20))
    search = request.GET.get('search', '')
    page = int(request.GET.get('page', 0))
    enabled_filter = request.GET.get('enabled', '')

    currencies = Currency.objects.filter(
        Q(name__contains=search) | Q(code__contains=search) | Q(symbol__contains=search)).order_by('code')
    if enabled_filter:
        if enabled_filter == "yes":
            currencies = currencies.filter(enabled=True)
        if enabled_filter == "no":
            currencies = currencies.filter(enabled=False)
    context.add_pagination_context(currencies, page, page_length, 'currencies')

    context["page_number"] = page
    context["page_length"] = generate_page_length_options(page_length)
    context["search"] = search
    context["enabledFilter"] = {
        "yes": (enabled_filter == "yes"),
        "none": (enabled_filter == ""),
        "no": (enabled_filter == "no"),
        "val": enabled_filter,
    }

    return render(request, template_name="admin/finance/currencies.html", context=context)


@admin_login_required
def admin_finance_methods(request):
    context = Context(request)

    if request.method == 'GET':
        form = CreatePaymentMethodForm()
    elif request.method == 'POST':
        method = PaymentMethod()
        form = CreatePaymentMethodForm(request.POST, instance=method)
        if form.is_valid():
            form.save()
            messages.success(request, "Method created successfully")
            form = CreatePaymentMethodForm()
        else:
            context["showModal"] = True

    else:
        # TODO Replace with proper handler
        assert False
    context['form'] = form
    page_length = int(request.GET.get('page_length', 20))
    search = request.GET.get('search', '')
    page = int(request.GET.get('page', 0))
    currency_filter = int(request.GET['currency']) if 'currency' in request.GET else None

    methods = PaymentMethod.objects.filter(Q(name__contains=search) | Q(currency__name__contains=search)).filter(
        currency__enabled=True)
    if currency_filter:
        methods = methods.filter(currency__pk=currency_filter)

    context.add_pagination_context(methods, page, page_length, 'methods')

    context["page_number"] = page
    context["page_length"] = generate_page_length_options(page_length)
    context["search"] = search
    return render(request, "admin/finance/methods.html", context)


@admin_login_required
def admin_finance_methods_delete(request):
    if request.method == "POST":
        if "id" in request.POST:
            try:
                method = PaymentMethod.objects.get(id=uuid.UUID(request.POST["id"]))
                method.delete()
                messages.success(request, "The payment method was successfully deleted")
            except PaymentMethod.DoesNotExist:
                messages.warning(request, "The specified Payment method doesn't exist")
            except ProtectedError:
                messages.error(request, "The specified method can't be deleted as other records such as "
                                        "payments or tills depend on it. You can remove it from the deposits "
                                        "to prevent further use.")
    return redirect("admin/finance/methods")


@admin_login_required
def admin_units_overview(request):
    context = Context(request)
    if request.method == "POST":
        if check_dict(request.POST, ['newUnitGroupName', 'newUnitGroupSymbol']):
            group = UnitGroup()
            group.name = request.POST['newUnitGroupName']
            group.symbol = request.POST['newUnitGroupSymbol']
            group.save()
            messages.success(request, "The unit group was created successfully")
        if check_dict(request.POST, ['groupId', 'newUnitName', 'newUnitSymbol', 'newUnitRatio']):
            group_id = uuid.UUID(request.POST['groupId'])
            try:
                unit = Unit()
                unit.name = request.POST['newUnitName']
                unit.symbol = request.POST['newUnitSymbol']
                unit.ratio = float(request.POST['newUnitRatio'])
                unit.group = UnitGroup.objects.get(id=group_id)
                unit.save()
                messages.success(request, "The unit was created successfully")
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

    return render(request, template_name='admin/units/overview.html', context=context)


class Admin:
    class Menu:
        class Products(views.View):
            def fill_data(self, request):
                context = Context(request)
                page_length = int(request.GET.get('page_length', 20))
                search = request.GET.get('search', '')
                page = int(request.GET.get('page', 0))
                enabled_filter = request.GET.get('enabled', '')

                products = Product.objects.filter(name__contains=search).order_by('name')
                if enabled_filter:
                    if enabled_filter == "yes":
                        products = products.filter(enabled=True)
                    if enabled_filter == "no":
                        products = products.filter(enabled=False)
                context.add_pagination_context(products, page, page_length, 'products')

                context["page_number"] = page
                context["page_length"] = generate_page_length_options(page_length)
                context["search"] = search
                context["enabledFilter"] = {
                    "yes": (enabled_filter == "yes"),
                    "none": (enabled_filter == ""),
                    "no": (enabled_filter == "no"),
                    "val": enabled_filter,
                }

                return context

            def get(self, request, *args, **kwargs):
                context = self.fill_data(request)
                context["create_product_form"] = CreateEditProductForm()

                return render(request, 'admin/menu/products/index.html', context)

            def post(self, request, *args, **kwargs):
                product = Product()
                form = CreateEditProductForm(request.POST, instance=product)
                if form.is_valid():
                    form.save()
                    messages.success(request, "Product created successfully")
                    return redirect("admin/menu/products/product", id=product.id)
                else:
                    context = self.fill_data(request)
                    context["create_product_form"] = form

                    return render(request, "admin/menu/products/index.html", context)

            class Product(views.View):
                def get(self, request, id, *args, **kwargs):
                    context = Context(request)
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
                    return render(request, 'admin/menu/products/product.html', context)

                def post(self, request, id, *args, **kwargs):
                    context = Context(request)
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
                    return render(request, 'admin/menu/products/product.html', context)

                class Delete(views.View):
                    def get(self, request, id, *args, **kwargs):
                        try:
                            product = Product.objects.get(id=id)
                            product.delete()
                            messages.success(request, f"Product {product.name} was deleted.")
                            return redirect("admin/menu/products")
                        except Product.DoesNotExist:
                            return redirect("admin/menu/products/product", id=id)
                        except ProtectedError:
                            messages.error(request, "This Product can't be deleted as it was already ordered")
                            return redirect("admin/menu/products/product", id=id)

        class Items(views.View):
            def get(self, request):
                context = Context(request)
                items = Item.objects.all()
                context.add_pagination_context(items, 0, 20, "items")
                return render(request, 'admin/menu/items.html', context)

            class Item(views.View):
                def get(self, request, id):
                    messages.info(request, "That link leads nowhere, you better be safe.")
                    return redirect("admin/menu/items")

                class Delete(views.View):
                    def get(self, request, id):
                        pass

