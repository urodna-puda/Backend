from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from posapp.models import Tab
from posapp.serializers import TabListSerializer
import json


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

