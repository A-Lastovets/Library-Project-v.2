from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
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
from app.services.user_service import librarian_ws_required, librarian_required
from app.websockets.chat_queue_manager import chat_queue_manager
from app.websockets.chat_room_manager import chat_room_manager
from app.utils import decode_jwt_token
import logging

router = APIRouter(tags=["Chat"])

logger = logging.getLogger(__name__)

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
        reader_id=current_user.id,
        status="pending"
    )
    db.add(session)
    await db.flush()  # потрібно для отримання session.id до створення повідомлення

    # Збереження першого повідомлення
    message = ChatMessage(
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
    try:
        # Перевірка токена ДО accept
        librarian_data = await librarian_ws_required(websocket)

        # Якщо пройшло — приймаємо підключення
        await websocket.accept()
    except Exception as e:
        print("❌ Auth WS queue error:", e)
        await websocket.close(code=1008)
        return

    await chat_queue_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        chat_queue_manager.disconnect(websocket)



@router.post("/chat/{session_id}/assign")
async def take_chat(
    session_id: int,
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
async def private_chat_ws(websocket: WebSocket, room_id: int, db: AsyncSession = Depends(get_db)):
    logger.info(f"📦 WebSocket headers: {websocket.headers}")
    logger.info(f"📦 WebSocket cookies: {websocket.cookies}")
    token = websocket.cookies.get("access_token")

    if not token:
        logger.warning("❌ Немає access_token в куках!")
        await websocket.close(code=1008)
        return

    try:
        user_data = decode_jwt_token(token)
        logger.info(f"📨 Decoded token: {user_data}")
        user_id = int(user_data.get("id"))
        role = user_data.get("role")
        logger.info(f"🪪 TOKEN USER ID: {user_id} | ROLE: {role}")
    except Exception as e:
        logger.error(f"❌ decode error: {e.__class__.__name__} - {e}")
        await websocket.close(code=1008)
        return
    
    result = await db.execute(select(ChatSession).where(ChatSession.id == room_id))
    session = result.scalar_one_or_none()

    if session is None:
        logger.warning("❌ Сесія не знайдена!")
        await websocket.close(code=1008)
        return
    
    allowed_ids = {id for id in [session.reader_id, session.librarian_id] if id is not None}
    logger.info(f"📦 allowed_ids: {allowed_ids}, type={type(list(allowed_ids)[0]) if allowed_ids else 'empty'}")

    logger.info(f"📦 ВСІ Сесії: {session}")
    logger.info(f"📦 user_id={user_id}, читач={session.reader_id}, бібліотекар={session.librarian_id}")
    logger.info(f"📦 allowed_ids: {allowed_ids}")

    if int(user_id) not in allowed_ids:
        logger.warning("🚫 Доступ до чату заборонено.")
        await websocket.close(code=1008)
        return

    await websocket.accept()

    user = await db.get(User, user_id)
    full_name = f"{user.first_name} {user.last_name}"
    display_role = "Читач" if role == "reader" else "Бібліотекар"

    await chat_room_manager.connect(room_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()

            if "typing" in data:
                await chat_room_manager.send_to_room(room_id, {
                    "info": f"{display_role} пише..." if data["typing"] else "",
                    "sender_full_name": full_name,
                    "typing": data["typing"]
                })
                continue

            text = data.get("message")
            if not text:
                continue

            result = await db.execute(select(ChatSession).where(ChatSession.id == room_id))
            session = result.scalar_one_or_none()
            if not session or session.status == "closed":
                await websocket.send_json({"info": "Цей чат завершено. Нові повідомлення недоступні."})
                continue

            message = ChatMessage(session_id=room_id, sender_id=user_id, message=text)
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
    session_id: int,
    db: AsyncSession = Depends(get_db),
    librarian_data: dict = Depends(librarian_ws_required)
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
