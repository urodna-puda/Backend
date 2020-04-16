from asgiref.sync import async_to_sync
from channels.generic.websocket import AsyncJsonWebsocketConsumer, JsonWebsocketConsumer


class Notifications:
    class User(JsonWebsocketConsumer):
        def connect(self):
            self.user = self.scope["user"]

            if not self.user.is_authenticated:
                self.close(4401)
            else:
                self.accept()

            self.channel_layer.group_add(f"user-{self.user.username}", self.channel_name)

        def disconnect(self, code):
            self.channel_layer.group_discard(f"user-{self.user.username}", self.channel_name)

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
            self.send_json({
                "notification_type": "void_request",
                "request_id": str(void_request.id),
                "user": {
                    "first_name": void_request.waiter.first_name,
                    "last_name": void_request.waiter.last_name,
                    "username": void_request.waiter.username,
                },
                "order": {
                    "id": str(void_request.order.id),
                    "product_name": void_request.order.product.name,
                    "state": void_request.order.state,
                    "ordered_at": str(void_request.order.orderedAt),
                    "preparing_at": str(void_request.order.preparingAt),
                    "prepared_at": str(void_request.order.preparedAt),
                    "served_at": str(void_request.order.servedAt),
                    "note": void_request.order.note,
                    "tab_name": void_request.order.tab.name,
                }
            })
