from typing import List
from fastapi import WebSocket

class ChatQueueManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_new_chat(self, session_data: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json({
                    "event": "new_chat",
                    "data": session_data
                })
            except Exception as e:
                print(f"❌ Не вдалося надіслати повідомлення: {e}")


chat_queue_manager = ChatQueueManager()
