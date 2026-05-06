# Massive live dashboard

A self-contained streaming-quotes dashboard for [Massive.com](https://massive.com).

- One FastAPI process opens a single websocket to `wss://socket.massive.com/stocks`
  using your `MASSIVE_API_KEY` (server-side; the key never reaches the browser).
- A single HTML page connects to the backend over `/ws` and renders live
  trade prices, NBBO bid/ask, day OHLC, and volume with green/red flashes on
  every tick.
- Add tickers from the browser; subscriptions are reference-counted so
  multiple browsers can watch overlapping symbols efficiently.

## Run

```bash
pip install fastapi uvicorn websockets
MASSIVE_API_KEY=your_key uvicorn dashboard.server:app --port 9000
```

Open <http://localhost:9000>.

## Channels

Each ticker subscribes to three Massive channels:
- `T.<sym>` — tick-level trades
- `Q.<sym>` — NBBO quotes (bid/ask + sizes)
- `AM.<sym>` — per-minute aggregates (day OHLC/volume)

## Customizing

- `MASSIVE_WS_URL` — override the upstream host (default
  `wss://socket.massive.com/stocks`).
- Edit `dashboard/index.html` to restyle. No build step.
