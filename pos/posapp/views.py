from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

# Create your views here.
from posapp.models import Tab, ProductInTab, Product
from posapp.security import waiter_login_required, manager_login_required


def prepare_context(request):
    return {
        'page': request.get_full_path()[1:],
        'waiter_role': request.user.is_waiter,
        'manager_role': request.user.is_manager,
        'staff_role': request.user.is_staff,
    }


@login_required
def index(request):
    return redirect("waiter/tabs")


@waiter_login_required
def waiter_tabs(request):
    context = prepare_context(request)
    tabs = []
    tabs_list = Tab.objects.filter(state=Tab.OPEN)
    for tab in tabs_list:
        out = {
            'name': tab.name,
            'id': tab.id,
            'total': tab.total,
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

        for product in products:
            variants = []
            for variant in products[product]['variants']:
                variants.append(products[product]['variants'][variant])

            out['products'].append({
                'id': products[product]['id'],
                'name': products[product]['name'],
                'variants': variants,
            })

        tabs.append(out)

    context['tabs'] = tabs
    context['products'] = []
    for product in Product.objects.all():
        context['products'].append({
            'id': product.id,
            'name': product.name,
        })
    return render(request, template_name="waiter/tabs.html", context=context)


@waiter_login_required
def waiter_orders(request):
    context = prepare_context(request)
    return render(request, template_name="waiter/orders.html", context=context)


@manager_login_required
def manager_waiters_overview(request):
    context = prepare_context(request)
    return render(request, template_name="manager/waiters/overview.html", context=context)


@manager_login_required
def manager_waiters_assign(request):
    context = prepare_context(request)
    return render(request, template_name="manager/waiters/assign.html", context=context)
