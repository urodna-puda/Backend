from channels.generic.websocket import WebsocketConsumer
import json


class Notifications:
    class Manager(WebsocketConsumer):
        groups = ["notifications_manager"]

        def connect(self):
            self.user = self.scope["user"]

            if not self.user.is_authenticated:
                self.close(4901)
            elif not self.user.is_manager:
                self.close(4903)
            else:
                self.accept()
