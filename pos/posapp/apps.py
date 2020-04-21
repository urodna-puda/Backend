from django.apps import AppConfig
from django.db import OperationalError


class PosappConfig(AppConfig):
    name = 'posapp'

    def ready(self):
        User = self.get_model('User')
        try:
            User.objects.all().update(online_counter=0)
        except OperationalError:
            print("Database is not yet created. We can ignore this, as the counters will start at zero anyway.")
