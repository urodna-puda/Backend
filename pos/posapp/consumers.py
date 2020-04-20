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
            self.send_json({
                "notification_type": "void_request_resolved",
                "request_id": str(void_request.id),
                "manager": {
                    "first_name": void_request.manager.first_name,
                    "last_name": void_request.manager.last_name,
                    "username": void_request.manager.username,
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
                    "tab_id": str(void_request.order.tab.id),
                },
                "resolution": void_request.resolution,
            })

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

        def notification_tab_transfer_request(self, event):
            print(f"notification received by channel {self.channel_name}")
            transfer_request = event["tab_transfer_request"]
            self.send_json({
                "notification_type": "tab_transfer_request",
                "request_id": str(transfer_request.id),
                "tab_name": transfer_request.tab.name,
                "requester_name": transfer_request.requester.name,
                "new_owner_name": transfer_request.new_owner.name,
                "transfer_mode": event["transfer_mode"],
            })
            print("notification sent to client")
