from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from posapp.models import Tab, Product
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
