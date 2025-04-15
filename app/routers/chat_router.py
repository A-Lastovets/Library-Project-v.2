from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4, UUID
from sqlalchemy import select
from app.models.chat import ChatSession, ChatMessage
from app.models.user import User
from app.schemas.schemas import (
        ChatStartRequest, ChatSessionResponse, 
        ChatTakeRequest, ChatCloseRequest,
        ChatMessageResponse
)
from app.dependencies.database import get_db
from app.services.user_service import get_current_user
from fastapi import WebSocket, WebSocketDisconnect
from app.services.user_service import librarian_required
from app.websockets.chat_queue_manager import chat_queue_manager
from app.websockets.chat_room_manager import chat_room_manager
from app.utils import decode_jwt_token

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/start", response_model=ChatSessionResponse)
async def start_chat(
    payload: ChatStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "reader":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only readers can initiate chats.")

    # Перевірка: чи вже є активна сесія?
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.reader_id == current_user.id,
            ChatSession.status.in_(["pending", "active"])
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="You already have an active chat session.")

    # Створення нової сесії
    session = ChatSession(
        id=uuid4(),
        reader_id=current_user.id,
        status="pending"
    )
    db.add(session)
    await db.flush()  # потрібно для отримання session.id до створення повідомлення

    # Збереження першого повідомлення
    message = ChatMessage(
        id=uuid4(),
        session_id=session.id,
        sender_id=current_user.id,
        message=payload.message
    )
    db.add(message)
    await db.commit()

    # Надсилаємо live-подію бібліотекарям
    await chat_queue_manager.broadcast_new_chat({
        "session_id": str(session.id),
        "reader_id": str(session.reader_id),
        "status": session.status,
        "created_at": session.created_at.isoformat()
    })

    return ChatSessionResponse(
        session_id=session.id,
        status=session.status,
        created_at=session.created_at
    )


@router.websocket("/ws/queue")
async def librarian_queue_ws(websocket: WebSocket):
    _ = await librarian_required(websocket)
    await chat_queue_manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        chat_queue_manager.disconnect(websocket)


@router.post("/chat/{session_id}/assign")
async def take_chat(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    librarian_data: dict = Depends(librarian_required)
):
    librarian_id = int(librarian_data["id"])

    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.status == "pending"
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found or already taken.")

    session.librarian_id = librarian_id
    session.status = "active"
    await db.commit()

    return {"detail": "Chat session assigned", "room_id": str(session.id)}


@router.websocket("/ws/chat/{room_id}")
async def private_chat_ws(websocket: WebSocket, room_id: str, db: AsyncSession = Depends(get_db)):
    await websocket.accept()

    token = websocket.cookies.get("access_token")
    if not token:
        await websocket.close(code=1008)
        return

    try:
        user_data = decode_jwt_token(token)
    except Exception:
        await websocket.close(code=1008)
        return

    user_id = int(user_data["id"])
    role = user_data["role"]
    user = await db.get(User, user_id)
    full_name = f"{user.first_name} {user.last_name}"
    display_role = "Читач" if role == "reader" else "Бібліотекар"

    result = await db.execute(select(ChatSession).where(ChatSession.id == room_id))
    session = result.scalar_one_or_none()
    if not session or (user_id not in [session.reader_id, session.librarian_id]):
        await websocket.close(code=1008)
        return

    await chat_room_manager.connect(room_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()

            # Обробка: користувач "пише"
            if "typing" in data:
                if data["typing"]:
                    await chat_room_manager.send_to_room(room_id, {
                        "info": f"{display_role} пише...",
                        "sender_full_name": full_name,
                        "typing": True
                    })
                else:
                    await chat_room_manager.send_to_room(room_id, {
                        "typing": False
                    })
                continue

            # Обробка повідомлення
            text = data.get("message")
            if not text:
                continue
            
            # 🔒 Перевіряємо, чи чат вже завершено
            result = await db.execute(select(ChatSession).where(ChatSession.id == room_id))
            session = result.scalar_one_or_none()
            if not session or session.status == "closed":
                await websocket.send_json({"info": "Цей чат завершено. Нові повідомлення недоступні."})
                continue

            message = ChatMessage(
                id=uuid4(),
                session_id=room_id,
                sender_id=user_id,
                message=text
            )
            db.add(message)
            await db.commit()

            await chat_room_manager.send_to_room(room_id, {
                "from": display_role,
                "sender_full_name": full_name,
                "message": text
            })

    except WebSocketDisconnect:
        chat_room_manager.disconnect(room_id, websocket)


@router.post("/chat/{session_id}/close")
async def close_chat(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    librarian_data: dict = Depends(librarian_required)
):
    librarian_id = int(librarian_data["id"])

    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.librarian_id == librarian_id,
            ChatSession.status == "active"
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Active chat not found.")

    session.status = "closed"
    await db.commit()

    # Сповіщення у кімнаті
    await chat_room_manager.send_to_room(str(session.id), {
    "event": "closed",
    "info": "Чат завершено бібліотекарем"
    })
    
    return {"detail": "Chat closed successfully."}


@router.get("/history", response_model=list[ChatMessageResponse])
async def get_full_chat_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Отримати всі сесії користувача
    result = await db.execute(
        select(ChatSession.id).where(ChatSession.reader_id == current_user.id)
    )
    session_ids = [row[0] for row in result.all()]
    if not session_ids:
        return []

    # 2. Отримати всі повідомлення
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id.in_(session_ids))
        .order_by(ChatMessage.timestamp)
    )
    messages = result.scalars().all()
    if not messages:
        return []

    # 3. Отримати всіх користувачів, які надсилали повідомлення
    sender_ids = list({msg.sender_id for msg in messages})
    result = await db.execute(
        select(User.id, User.first_name, User.last_name).where(User.id.in_(sender_ids))
    )
    users = {row.id: f"{row.first_name} {row.last_name}" for row in result.all()}

    # 4. Побудувати відповідь
    return [
        ChatMessageResponse(
            message=m.message,
            sender_id=m.sender_id,
            sender_full_name=users.get(m.sender_id, "Unknown user"),
            session_id=m.session_id,
            timestamp=m.timestamp
        )
        for m in messages
    ]
