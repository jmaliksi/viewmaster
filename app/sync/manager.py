import uuid
from fastapi import WebSocket


class SyncSession:
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.host: WebSocket | None = None
        self.clients: list[WebSocket] = []
        self.state: dict | None = None


class SyncManager:
    def __init__(self):
        self.session: SyncSession | None = None

    def register_host(self, ws: WebSocket) -> bool:
        if self.session and self.session.host is not None and self.session.host is not ws:
            if self.session.host.client_state.value == 1:
                return False
        if self.session is None:
            self.session = SyncSession()
        self.session.host = ws
        return True

    def attach_client(self, ws: WebSocket) -> dict | None:
        if self.session is None:
            self.session = SyncSession()
        self.session.clients.append(ws)
        return self.session.state if self.session.host is not None else None

    def update_state(self, ws: WebSocket, state: dict) -> bool:
        if self.session is None or self.session.host is None or self.session.host is not ws:
            return False
        self.session.state = state
        return True

    def remove(self, ws: WebSocket) -> str | None:
        if self.session is None:
            return None
        if self.session.host is ws:
            was_host = True
            self.session.host = None
        else:
            was_host = False
            if ws in self.session.clients:
                self.session.clients.remove(ws)
        if self.session.host is None and not self.session.clients:
            self.session = None
        return "host" if was_host else "client"

    def get_clients(self) -> list[WebSocket]:
        if self.session is None:
            return []
        return list(self.session.clients)

    def get_host(self) -> WebSocket | None:
        if self.session is None:
            return None
        return self.session.host

    def has_host(self) -> bool:
        return self.session is not None and self.session.host is not None

    @property
    def connected_client_count(self) -> int:
        if self.session is None:
            return 0
        return len(self.session.clients)


manager = SyncManager()
