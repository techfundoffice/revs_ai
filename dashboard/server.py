"""Streaming-quotes dashboard backend.

Run::

    pip install fastapi uvicorn websockets
    MASSIVE_API_KEY=your_key uvicorn dashboard.server:app --port 9000

Then open http://localhost:9000 in a browser.

Architecture
------------
- The user's Massive API key is read from the env var and lives ONLY in this
  process — it is never sent to the browser.
- ``GET /`` serves the single-file frontend (``dashboard/index.html``).
- ``WS /ws`` is the browser bridge: the browser sends ``{"action":"subscribe",
  "tickers":["AAPL","MSFT"]}`` and the server forwards trade/quote events as
  JSON.  Only one upstream Massive websocket is opened per backend process,
  shared across browsers.
- Channels: ``T.<sym>`` (trades), ``Q.<sym>`` (NBBO quotes), ``AM.<sym>``
  (per-minute aggregates).  Wildcard subscriptions are not exposed to keep
  per-user message volume bounded.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import websockets
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

logger = logging.getLogger("massive_dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

MASSIVE_WS_URL = os.environ.get(
    "MASSIVE_WS_URL", "wss://socket.massive.com/stocks"
)
MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY", "")
INDEX_HTML_PATH = Path(__file__).parent / "index.html"

app = FastAPI(title="Massive live dashboard")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    if not INDEX_HTML_PATH.exists():
        raise HTTPException(500, "index.html missing")
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "key_configured": bool(MASSIVE_API_KEY)}


# ---------------------------------------------------------------------------
# Upstream Massive websocket session, shared across browser clients.
# ---------------------------------------------------------------------------


class MassiveBridge:
    """Single connection to Massive, fanning events out to browser clients."""

    def __init__(self) -> None:
        self._upstream: websockets.WebSocketClientProtocol | None = None
        self._subscribers: set[WebSocket] = set()
        # ref-count subscriptions per channel so we only unsubscribe upstream
        # when the last browser client drops it.
        self._channel_refcount: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._reader_task: asyncio.Task | None = None

    async def ensure_connected(self) -> None:
        async with self._lock:
            if self._upstream is not None:
                return
            if not MASSIVE_API_KEY:
                raise RuntimeError("MASSIVE_API_KEY is not set in the server environment")
            logger.info("connecting upstream %s", MASSIVE_WS_URL)
            ws = await websockets.connect(MASSIVE_WS_URL, max_size=2**20)
            await ws.send(json.dumps({"action": "auth", "params": MASSIVE_API_KEY}))
            # Wait for an auth_success status event.
            for _ in range(5):
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                events = self._parse_events(raw)
                if any(e.get("ev") == "status" and e.get("status") in ("auth_success", "connected") for e in events):
                    continue
                if any(e.get("ev") == "status" and e.get("status") == "auth_success" for e in events):
                    break
                if any(e.get("ev") == "status" and e.get("status") == "auth_failed" for e in events):
                    await ws.close()
                    raise RuntimeError("Massive auth_failed — check MASSIVE_API_KEY")
            self._upstream = ws
            self._reader_task = asyncio.create_task(self._reader_loop())

    @staticmethod
    def _parse_events(raw: str | bytes) -> list[dict[str, Any]]:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    async def _reader_loop(self) -> None:
        ws = self._upstream
        assert ws is not None
        try:
            async for raw in ws:
                events = self._parse_events(raw)
                if not events:
                    continue
                # Fan out to subscribers
                dead: list[WebSocket] = []
                payload = json.dumps(events)
                for client in list(self._subscribers):
                    try:
                        await client.send_text(payload)
                    except (WebSocketDisconnect, RuntimeError):
                        dead.append(client)
                for d in dead:
                    self._subscribers.discard(d)
        except websockets.ConnectionClosed:
            logger.warning("upstream connection closed")
        finally:
            self._upstream = None

    async def add_subscriber(self, client: WebSocket) -> None:
        self._subscribers.add(client)

    async def remove_subscriber(self, client: WebSocket, channels: set[str]) -> None:
        self._subscribers.discard(client)
        await self._unsubscribe_channels(channels)

    async def subscribe_channels(self, channels: set[str]) -> None:
        new_channels: list[str] = []
        for ch in channels:
            count = self._channel_refcount.get(ch, 0)
            self._channel_refcount[ch] = count + 1
            if count == 0:
                new_channels.append(ch)
        if new_channels and self._upstream is not None:
            await self._upstream.send(json.dumps({"action": "subscribe", "params": ",".join(new_channels)}))

    async def _unsubscribe_channels(self, channels: set[str]) -> None:
        drop: list[str] = []
        for ch in channels:
            count = self._channel_refcount.get(ch, 0) - 1
            if count <= 0:
                self._channel_refcount.pop(ch, None)
                drop.append(ch)
            else:
                self._channel_refcount[ch] = count
        if drop and self._upstream is not None:
            with contextlib.suppress(Exception):
                await self._upstream.send(json.dumps({"action": "unsubscribe", "params": ",".join(drop)}))


bridge = MassiveBridge()


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """Browser bridge.

    Inbound:  ``{"action":"subscribe","tickers":["AAPL","MSFT"]}``
              ``{"action":"unsubscribe","tickers":["AAPL"]}``
    Outbound: arrays of Massive events, e.g. ``[{"ev":"T","sym":"AAPL",...}]``
    """
    await websocket.accept()
    client_channels: set[str] = set()
    try:
        await bridge.ensure_connected()
    except Exception as exc:
        await websocket.send_text(json.dumps([{"ev": "error", "message": str(exc)}]))
        await websocket.close()
        return

    await bridge.add_subscriber(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            tickers = [t.strip().upper() for t in (msg.get("tickers") or []) if isinstance(t, str)]
            if not tickers:
                continue
            channels = set()
            for t in tickers:
                channels.update({f"T.{t}", f"Q.{t}", f"AM.{t}"})
            action = msg.get("action")
            if action == "subscribe":
                new = channels - client_channels
                client_channels |= channels
                if new:
                    await bridge.subscribe_channels(new)
            elif action == "unsubscribe":
                drop = channels & client_channels
                client_channels -= channels
                if drop:
                    # Only unref once per client, regardless of subscribe count.
                    await bridge._unsubscribe_channels(drop)
    except WebSocketDisconnect:
        pass
    finally:
        await bridge.remove_subscriber(websocket, client_channels)
