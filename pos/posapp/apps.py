from django.apps import AppConfig


class PosappConfig(AppConfig):
    name = 'posapp'

    def ready(self):
        User = self.get_model('User')
        User.objects.all().update(online_counter=0)
