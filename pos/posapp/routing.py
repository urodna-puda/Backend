from channels.routing import URLRouter
from django.urls import path

from posapp import consumers

websocket_urlpatterns = URLRouter([
    path('notifications/user', consumers.Notifications.User),
    path('notifications/manager', consumers.Notifications.Manager),
])
