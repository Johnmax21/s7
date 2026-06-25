import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import os


       
class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_code']
        self.room_group = f"s7app_{self.room_name}"
        self.user = self.scope["user"]
        print(f"🔌 WS CONNECT: user={self.user}, room={self.room_name}, PID={os.getpid()}")
        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.room_group, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")
        if action == "ping":
            await self.send(json.dumps({"type": "pong"}))
    async def player_joined(self, event):
        await self.send(json.dumps(event))
    async def innings_chosen(self, event):
        await self.send(json.dumps(event))
    # ── Broadcast handlers ──────────────────────────
    async def player_joined(self, event):
        await self.send(json.dumps(event))

    async def player_exit(self, event):
        await self.send(json.dumps(event))

    async def toss_result(self, event):
        await self.send(json.dumps(event))

    async def round_result(self, event):
        await self.send(json.dumps(event))

    # ── NEW: Specific signals ───────────────────────
    async def card_played(self, event):
        """Sent when ONE player plays a card — tells waiting player to reload"""
        await self.send(json.dumps(event))

    async def innings_over(self, event):
        """Sent when innings ends"""
        await self.send(json.dumps(event))

    async def game_over(self, event):
        """Sent when game ends"""
        await self.send(json.dumps(event))
    async def round_result(self, event):
        await self.send(json.dumps(event))  # round key already included
    async def boost_applied(self, event):
        await self.send(json.dumps(event))