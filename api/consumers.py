import json
from django.db.models import Q
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Workstation

class WorkstationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.workstation_id = self.scope['url_route']['kwargs']['workstation_id']
        self.group_name = f'workstation_{self.workstation_id}'

        user = self.scope['user']

        if user.is_anonymous or not await self.is_member(user, self.workstation_id):
            await self.close()
            return

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

        # Send initial DB content to gracefully resume state
        workstation = await self.get_workstation()
        if workstation and workstation.content:
            # We only send if content is not Yjs binary (avoiding confusion for older text clients)
            if not workstation.content.startswith('yjs:'):
                await self.send(text_data=json.dumps({
                    "type": "initial_content",
                    "content": workstation.content
                }))


    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        user = self.scope['user']
        if not user.is_anonymous:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'presence_update',
                    'user': user.email,
                    'action': 'leave'
                }
            )

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            # Broadcast bytes to group instantly (Y-Websocket sync packets)
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_bytes',
                    'bytes_data': bytes_data,
                    'sender_channel_name': self.channel_name
                }
            )
        elif text_data:
            try:
                data = json.loads(text_data)
                if data.get('type') == 'cursor_update':
                    await self.channel_layer.group_send(
                        self.group_name,
                        {
                            'type': 'cursor_update',
                            'x': data['x'],
                            'y': data['y'],
                            'sender_email': getattr(self.scope['user'], 'email', 'unknown'),
                            'sender_channel_name': self.channel_name
                        }
                    )
            except json.JSONDecodeError:
                pass

    async def cursor_update(self, event):
        if self.channel_name != event['sender_channel_name']:
            await self.send(text_data=json.dumps({
                'type': 'cursor_update',
                'x': event['x'],
                'y': event['y'],
                'sender_email': event['sender_email']
            }))


    async def broadcast_bytes(self, event):
        if self.channel_name != event['sender_channel_name']:
            await self.send(bytes_data=event['bytes_data'])

    async def presence_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'presence_update',
            'user': event['user'],
            'action': event['action']
        }))

    @database_sync_to_async
    def is_member(self, user, workstation_id):
        return Workstation.objects.filter(
            Q(id=workstation_id, owner=user) | 
            Q(id=workstation_id, members__user=user)
        ).exists()

    @database_sync_to_async
    def get_workstation(self):
        return Workstation.objects.filter(id=self.workstation_id).first()
