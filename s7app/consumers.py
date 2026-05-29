import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_code']
        self.room_group = f"s7app_{self.room_name}"
        self.user = self.scope["user"]

        # Join room group
        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()

        # Notify others someone joined
        await self.channel_layer.group_send(self.room_group, {
            "type": "player_joined",
            "username": self.user.username,
        })

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.room_group, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")

        if action == "toss":
            await self.handle_toss(data)
        elif action == "play_card":
            await self.handle_card(data)

    async def handle_toss(self, data):
        # your existing toss logic here
        result = "heads"  # compute randomly
        await self.channel_layer.group_send(self.room_group, {
            "type": "toss_result",
            "result": result,
            "winner": data["choice"] == result and self.user.username,
        })

    async def handle_card(self, data):
        # your existing round logic here
        await self.channel_layer.group_send(self.room_group, {
            "type": "round_result",
            "player": self.user.username,
            "card_id": data["card_id"],
            "runs": 4,   # compute from your logic
            "wicket": False,
        })

    # These methods broadcast to the group
    async def player_joined(self, event):
        await self.send(json.dumps(event))

    async def toss_result(self, event):
        await self.send(json.dumps(event))

    async def round_result(self, event):
        await self.send(json.dumps(event))