from django.urls import re_path
from .consumers import WorkstationConsumer

websocket_urlpatterns = [
    re_path(r'ws/workstation/(?P<workstation_id>[^/]+)$', WorkstationConsumer.as_asgi())
]