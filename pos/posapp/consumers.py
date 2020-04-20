from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer


class Notifications:
    class User(JsonWebsocketConsumer):
        def connect(self):
            self.user = self.scope["user"]

            if not self.user.is_authenticated:
                self.close(4401)
            else:
                self.accept()

            async_to_sync(self.channel_layer.group_add)(f"notifications_user-{self.user.id}", self.channel_name)

        def disconnect(self, code):
            async_to_sync(self.channel_layer.group_discard)(f"notifications_user-{self.user.id}", self.channel_name)

        def notification_void_request_resolved(self, event):
            void_request = event["void_request"]
            self.send_json(void_request)

        def notification_tab_transfer_request_resolved(self, event):
            self.send_json({
                "notification_type": "tab_transfer_request_resolved",
                "message": event["message"],
                "resolution": event["resolution"],
            })

    class Manager(JsonWebsocketConsumer):
        groups = ["notifications_manager"]

        def connect(self):
            self.user = self.scope["user"]

            if not self.user.is_authenticated:
                self.close(4401)
            elif not self.user.is_manager:
                self.close(4403)
            else:
                self.accept()
                # async_to_sync(self.channel_layer.group_add)("notifications_manager", self.channel_name)

        def disconnect(self, code):
            async_to_sync(self.channel_layer.group_discard)("notifications_manager", self.channel_name)

        def notification_void_request(self, event):
            void_request = event["void_request"]
            self.send_json(void_request)

        def notification_tab_transfer_request(self, event):
            print(f"notification received by channel {self.channel_name}")
            transfer_request = event["tab_transfer_request"]
            self.send_json()
            print("notification sent to client")
