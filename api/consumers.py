import json
import base64
import asyncio
import redis
import os
from django.db.models import Q
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Workstation, WorkstationMember

class WorkstationConsumer(AsyncWebsocketConsumer):
    # Class-level state to track workstations that need saving
    _save_locks = set()

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

        # ✅ send initial DB content
        workstation = await self.get_workstation()
        if workstation and workstation.content:
            # We only send if content is not Yjs binary (avoiding confusion)
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
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_bytes',
                    'bytes_data': bytes_data,
                    'sender_channel_name': self.channel_name
                }
            )

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

    async def append_update(self, update_data):
        self.redis.rpush(self.redis_key, update_data)
        await self.schedule_db_save()

    async def get_full_state(self):
        updates = self.redis.lrange(self.redis_key, 0, -1)
        
        if not updates:
            db_state_b64 = await self.get_db_state()
            if db_state_b64:
                full_state = base64.b64decode(db_state_b64.replace('yjs:', '', 1))
                self.redis.rpush(self.redis_key, full_state)
                return full_state
            return None
            
        return b''.join(updates)

    @database_sync_to_async
    def get_db_state(self):
        try:
            ws = Workstation.objects.get(id=self.workstation_id)
            return ws.content if ws.content.startswith('yjs:') else None
        except Workstation.DoesNotExist:
            return None

    async def schedule_db_save(self):
        if self.workstation_id not in WorkstationConsumer._save_locks:
            WorkstationConsumer._save_locks.add(self.workstation_id)
            # Debounce: wait 5 seconds before saving to DB
            asyncio.create_task(self.deferred_save())

    async def deferred_save(self):
        await asyncio.sleep(5)
        try:
            state = await self.get_full_state()
            if state:
                state_b64 = "yjs:" + base64.b64encode(state).decode('utf-8')
                await self.update_workstation_content(state_b64)
        finally:
            WorkstationConsumer._save_locks.remove(self.workstation_id)

    @database_sync_to_async
    def update_workstation_content(self, content):
        Workstation.objects.filter(id=self.workstation_id).update(content=content)
