import json
from django.db import models
from django.db.models import Q
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Workstation, WorkstationMember

class WorkstationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.workstation_id = self.scope['url_route']['kwargs']['workstation_id']
        self.group_name = f'workstation_{self.workstation_id}'

        # Check if user is authenticated and is a member
        user = self.scope['user']
        if user.is_anonymous or not await self.is_member(user, self.workstation_id):
            await self.close(code=4003) # Custom close code for Permission Denied
            return

        # Join room group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

        # Update presence (optional, can broadcast join)
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'presence_update',
                'user': user.email,
                'action': 'join'
            }
        )

    async def disconnect(self, close_code):
        # Leave room group
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

    # Receive message from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get('type')

        if message_type == 'content_update':
            content = data.get('content')
            # Save to DB (throttled or on specific event)
            await self.save_workstation_content(self.workstation_id, content)
            
            # Broadcast to others in the group
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_content',
                    'content': content,
                    'sender_channel_name': self.channel_name
                }
            )

    # Receive content update from room group
    async def broadcast_content(self, event):
        if self.channel_name != event['sender_channel_name']:
            await self.send(text_data=json.dumps({
                'type': 'content_update',
                'content': event['content']
            }))

    # Receive presence update from room group
    async def presence_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'presence_update',
            'user': event['user'],
            'action': event['action']
        }))

    @database_sync_to_async
    def is_member(self, user, workstation_id):
        return Workstation.objects.filter(
            (models.Q(id=workstation_id, owner=user) | 
             models.Q(id=workstation_id, members__user=user))
        ).exists()

    @database_sync_to_async
    def save_workstation_content(self, workstation_id, content):
        Workstation.objects.filter(id=workstation_id).update(content=content)
