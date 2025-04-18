from typing import Dict, List, Optional
from fastapi import WebSocket

class ChatRoomManager:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, room_id: str | int, websocket: WebSocket):
        room_id = str(room_id)
        self.rooms.setdefault(room_id, []).append(websocket)

    def disconnect(self, room_id: str | int, websocket: WebSocket):
        room_id = str(room_id)
        if room_id in self.rooms and websocket in self.rooms[room_id]:
            self.rooms[room_id].remove(websocket)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    async def send_to_room(self, room_id: str | int, message: dict, exclude: Optional[WebSocket] = None):
        room_id = str(room_id)
        for ws in self.rooms.get(room_id, []):
            if ws != exclude:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    print(f"❌ Не вдалося надіслати повідомлення: {e}")

chat_room_manager = ChatRoomManager()
