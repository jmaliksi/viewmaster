from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, Depends
from typing import Optional
from jose import JWTError, jwt
from app.auth import SECRET_KEY, ALGORITHM, BEARER_TOKEN_COOKIE_NAME, get_users_db
from app.sync.manager import manager

router = APIRouter(prefix="/api")


async def get_ws_user(
    websocket: WebSocket,
):
    token = websocket.cookies.get(BEARER_TOKEN_COOKIE_NAME)
    if not token or not token.strip():
        token = websocket.query_params.get("token")
    if not token or not token.strip():
        raise WebSocketException(code=1008, reason="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise WebSocketException(code=1008, reason="Invalid token")
    except JWTError:
        raise WebSocketException(code=1008, reason="Invalid token")
    users_db = get_users_db()
    user = users_db.get(username)
    if user is None:
        raise WebSocketException(code=1008, reason="User not found")
    return user


@router.websocket("/ws/sync")
async def sync_websocket(
    websocket: WebSocket,
    user: dict = Depends(get_ws_user),
):
    await websocket.accept()
    role = None
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "register_host":
                if not manager.register_host(websocket):
                    await websocket.send_json({"type": "error", "message": "Host already registered"})
                    continue
                role = "host"
                await websocket.send_json({"type": "host_registered"})

            elif msg_type == "attach_client":
                current_state = manager.attach_client(websocket)
                role = "client"
                if current_state is not None:
                    await websocket.send_json({
                        "type": "session_joined",
                        "state": current_state,
                    })
                else:
                    await websocket.send_json({"type": "waiting_for_host"})
                host = manager.get_host()
                if host is not None:
                    try:
                        await host.send_json({"type": "client_joined"})
                    except Exception:
                        pass

            elif msg_type == "state_update":
                state = data.get("state", {})
                if manager.update_state(websocket, state):
                    clients = manager.get_clients()
                    for client in clients:
                        try:
                            await client.send_json({"type": "state_update", "state": state})
                        except Exception:
                            pass
                else:
                    await websocket.send_json({"type": "error", "message": "Not registered as host"})

            elif msg_type == "disconnect":
                break

    except WebSocketDisconnect:
        pass
    finally:
        removed_role = manager.remove(websocket)
        if removed_role == "host":
            clients = manager.get_clients()
            for client in clients:
                try:
                    await client.send_json({"type": "session_ended"})
                except Exception:
                    pass
        elif removed_role == "client":
            host = manager.get_host()
            if host is not None:
                try:
                    await host.send_json({"type": "client_left"})
                except Exception:
                    pass
