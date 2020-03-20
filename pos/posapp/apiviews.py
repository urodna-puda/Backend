import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from posapp.models import Tab, Product, User, PaymentMethod, Currency, ProductInTab
from posapp.security.role_decorators import WaiterLoginRequiredMixin, ManagerLoginRequiredMixin
from posapp.serializers import TabListSerializer


class OpenTabs(APIView):
    def get(self, request, format=None):
        tabs = Tab.objects.filter(state=Tab.OPEN)
        serializer = TabListSerializer(tabs, many=True)
        return Response(serializer.data)

    def post(self, request, format=None):
        created = []
        for tab in request.data:
            new = Tab(name=tab)
            new.save()
            created.append(new)
        return Response(TabListSerializer(created, many=True).data)


class AllTabs(APIView):
    def get(self, request, format=None):
        tabs = Tab.objects.all()
        serializer = TabListSerializer(tabs, many=True)
        return Response(serializer.data)


class TabOrder(APIView):
    def post(self, request, id, format=None):
        if "product" not in request.data or \
                "amount" not in request.data or \
                "note" not in request.data or \
                "state" not in request.data:
            return Response("Parts of JSON are missing", status.HTTP_400_BAD_REQUEST)
        tab = Tab.objects.get(id=id, state=Tab.OPEN)
        if tab is None:
            return Response("Tab not found", status.HTTP_404_NOT_FOUND)
        product = Product.objects.get(id=request.data['product'])
        if product is None:
            return Response("Product not found", status.HTTP_404_NOT_FOUND)
        tab.order_product(product, request.data['amount'], request.data['note'], request.data['state'])
        return Response("", status.HTTP_201_CREATED)


class Orders:
    class Order:
        class RequestVoid(WaiterLoginRequiredMixin, APIView):
            def get(self, request, id, format=None):
                try:
                    order = ProductInTab.objects.get(id=id)
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        "manager_notifications",
                        {
                            "type": "notification.void_request",
                            "request_id": uuid.uuid4(),
                            "user": request.user,
                            "order": order,
                        },
                    )
                    return Response(status=status.HTTP_501_NOT_IMPLEMENTED)
                except ProductInTab.DoesNotExist:
                    return Response(status=status.HTTP_404_NOT_FOUND)

        class Void(ManagerLoginRequiredMixin, APIView):
            def get(self, request, id, format=None):
                try:
                    order = ProductInTab.objects.get(id=id)
                    order.delete()
                    return Response(status=status.HTTP_200_OK)
                except ProductInTab.DoesNotExist:
                    return Response(status=status.HTTP_404_NOT_FOUND)


class UserToggles(APIView):
    is_text = "success\">is"
    isnt_text = "danger\">isn't"

    def post(self, request, username, role, format=None):
        if role not in ["waiter", "manager", "admin", "active"]:
            return Response({
                'status': 400,
                'error': f'role must be one of waiter/manager/admin/active, was {role}',
            }, status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(username=username)

            if request.user.can_grant(user, role):
                response = self.update_user(user, role)
                user.save()
            else:
                return Response({
                    'status': 403,
                    'error': 'A manager can only toggle waiter status or disable a waiter. '
                             'Admins can toggle anything except own admin and enabled status.',
                }, status.HTTP_403_FORBIDDEN)
            return response

        except ObjectDoesNotExist:
            return Response({
                'status': 404,
                'error': 'User with this username was not found',
            }, status.HTTP_404_NOT_FOUND)

    def update_user(self, user, role):
        if role == "waiter":
            user.is_waiter = not user.is_waiter
            new_state = user.is_waiter
            comment = "a waiter"
        elif role == "manager":
            user.is_manager = not user.is_manager
            new_state = user.is_manager
            comment = "a manager"
        elif role == "admin":
            user.is_admin = not user.is_admin
            new_state = user.is_admin
            comment = "an admin"
        elif role == "active":
            user.is_active = not user.is_active
            new_state = user.is_active
            comment = "active"
        else:
            assert False

        return Response({
            'status': 200,
            'now': new_state,
            'message': f"The user now <span class=\"badge badge-{self.is_text if new_state else self.isnt_text}</span> {comment}.",
        }, status.HTTP_200_OK)


class CurrencyToggleEnabled(APIView):
    is_text = "success\">is"
    isnt_text = "danger\">isn't"

    def post(self, request, id, format=None):
        if not request.user.is_admin:
            return Response({
                'status': 404,
                'error': 'Only admins can access this view',
            }, status.HTTP_403_FORBIDDEN)

        try:
            currency = Currency.objects.get(id=id)
            currency.enabled = not currency.enabled
            currency.save()
            return Response({
                'status': 200,
                'now': currency.enabled,
                'message': f"The currency now <span class=\"badge badge-{self.is_text if currency.enabled else self.isnt_text}</span> enabled.",
            }, status.HTTP_200_OK)

        except Currency.DoesNotExist:
            return Response({
                'status': 404,
                'error': 'Currency with this id was not found',
            }, status.HTTP_404_NOT_FOUND)


class MethodToggleChange(APIView):
    is_text = "success\">is"
    isnt_text = "danger\">isn't"

    def post(self, request, id, format=None):
        if not request.user.is_admin:
            return Response({
                'status': 404,
                'error': 'Only admins can access this view',
            }, status.HTTP_403_FORBIDDEN)

        try:
            method = PaymentMethod.objects.get(id=id)
            method.changeAllowed = not method.changeAllowed
            method.save()
            return Response({
                'status': 200,
                'now': method.changeAllowed,
                'message': f"The method now <span class=\"badge badge-{self.is_text if method.changeAllowed else self.isnt_text}</span> allowed as change.",
            }, status.HTTP_200_OK)

        except PaymentMethod.DoesNotExist:
            return Response({
                'status': 404,
                'error': 'Payment method with this id was not found',
            }, status.HTTP_404_NOT_FOUND)


class ProductToggleEnabled(APIView):
    is_text = "success\">is"
    isnt_text = "danger\">isn't"

    def post(self, request, id, format=None):
        if not request.user.is_admin:
            return Response({
                'status': 404,
                'error': 'Only admins can access this view',
            }, status.HTTP_403_FORBIDDEN)

        try:
            product = Product.objects.get(id=id)
            product.enabled = not product.enabled
            product.save()
            return Response({
                'status': 200,
                'now': product.enabled,
                'message': f"The product now <span class=\"badge badge-{self.is_text if product.enabled else self.isnt_text}</span> enabled.",
            }, status.HTTP_200_OK)

        except Product.DoesNotExist:
            return Response({
                'status': 404,
                'error': 'Product with this id was not found',
            }, status.HTTP_404_NOT_FOUND)
