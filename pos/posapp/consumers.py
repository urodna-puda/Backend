from channels.generic.websocket import WebsocketConsumer
import json


class ItemVoidRequestConsumer(WebsocketConsumer):
    def connect(self):
        self.room_name="waiter/tickers/void"

    def disconnect(self, code):
        pass

    def receive(self, text_data=None, bytes_data=None):
        pass
