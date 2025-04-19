from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
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
    await db.flush()

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
        created_at=session.created_at,
        reader_full_name=f"{current_user.first_name} {current_user.last_name}"
    )


@router.get("/chat/active-sessions", response_model=list[ChatSessionResponse])
async def get_active_chat_sessions(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required)
):
    result = await db.execute(
        select(ChatSession)
        .options(joinedload(ChatSession.reader))
        .where(ChatSession.status == "pending")
        .order_by(ChatSession.created_at)
    )
    sessions = result.scalars().all()

    return [
        ChatSessionResponse(
            session_id=session.id,
            status=session.status,
            created_at=session.created_at,
            reader_full_name=f"{session.reader.first_name} {session.reader.last_name}"
        )
        for session in sessions
    ]


@router.websocket("/ws/queue")
async def librarian_queue_ws(websocket: WebSocket):
    try:
        # Перевірка токена до accept
        _ = await librarian_ws_required(websocket)

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
    token = websocket.cookies.get("access_token")

    if not token:
        logger.warning("❌ Немає access_token в куках!")
        await websocket.close(code=1008)
        return

    try:
        user_data = decode_jwt_token(token)
        user_id = int(user_data.get("id"))
        role = user_data.get("role")
    except Exception as e:
        await websocket.close(code=1008)
        return
    
    result = await db.execute(select(ChatSession).where(ChatSession.id == room_id))
    session = result.scalar_one_or_none()

    if session is None:
        logger.warning("❌ Сесія не знайдена!")
        await websocket.close(code=1008)
        return
    
    allowed_ids = {id for id in [session.reader_id, session.librarian_id] if id is not None}

    if int(user_id) not in allowed_ids:
        logger.warning("🚫 Доступ до чату заборонено.")
        await websocket.close(code=1008)
        return

    await websocket.accept()

    user = await db.get(User, user_id)
    full_name = f"{user.first_name} {user.last_name}"
    display_role = "Читач" if role == "reader" else "Бібліотекар"

    await chat_room_manager.connect(room_id, websocket)

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == room_id)
        .order_by(ChatMessage.timestamp)
    )
    messages = result.scalars().all()

    for msg in messages:
        sender = await db.get(User, msg.sender_id)
        await websocket.send_json({
            "from": "Читач" if sender.role == "reader" else "Бібліотекар",
            "sender_full_name": f"{sender.first_name} {sender.last_name}",
            "message": msg.message,
            "sender_id": sender.id
        })

    try:
        while True:
            data = await websocket.receive_json()

            if "typing" in data:
                await chat_room_manager.send_to_room(room_id, {
                    "info": f"{display_role} пише..." if data["typing"] else "",
                    "sender_full_name": full_name,
                    "typing": data["typing"],
                    "sender_id": user_id
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

            # Спочатку показати автору його повідомлення
            await websocket.send_json({
                "from": display_role,
                "sender_full_name": full_name,
                "message": text,
                "sender_id": user_id
            })

            # Потім іншим учасникам
            await chat_room_manager.send_to_room(room_id, {
                "from": display_role,
                "sender_full_name": full_name,
                "message": text,
                "sender_id": user_id
            }, exclude=websocket)

    except WebSocketDisconnect:
        chat_room_manager.disconnect(room_id, websocket)

        # Повідомлення іншій стороні
        other_role = "Читач" if role == "librarian" else "Бібліотекар"
        notice = f"{display_role} покинув чат. Розмову завершено."

        result = await db.execute(select(ChatSession).where(ChatSession.id == room_id))
        session = result.scalar_one_or_none()
        if session:
            await chat_room_manager.send_to_room(room_id, {
                "event": "chat_closed",
                "info": notice
            })
            await db.delete(session)
            await db.commit()


@router.post("/chat/{session_id}/close")
async def close_chat(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    librarian_data: dict = Depends(get_current_user)
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

    # Повне видалення сесії (разом із повідомленнями)
    await db.delete(session)
    await db.commit()

    return {"detail": "Chat deleted successfully."}
