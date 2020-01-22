from rest_framework import serializers
from rest_framework.fields import SerializerMethodField

from posapp.models import Tab


class TabListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tab
        fields = ['id', 'name', 'state', 'openedAt', 'closedAt', 'totalSpent']

    totalSpent = SerializerMethodField()

    def get_totalSpent(self, obj):
        return obj.total
