import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, Plus, X as XIcon, Wifi, WifiOff } from "lucide-react";

/**
 * MassiveLive — real-time streaming dashboard wired to the Massive
 * websocket bridge served by ``dashboard/server.py`` (FastAPI).
 *
 * Set ``VITE_MASSIVE_WS_URL`` in the frontend env to point at the bridge,
 * e.g. ``ws://localhost:9000/ws`` for dev or ``wss://api.example.com/ws``
 * in production.  The user's Massive API key never reaches the browser —
 * it lives in the bridge process.
 */

type TickerState = {
  sym: string;
  price?: number;
  size?: number;
  bid?: number;
  ask?: number;
  bidSize?: number;
  askSize?: number;
  dayOpen?: number;
  dayHigh?: number;
  dayLow?: number;
  dayVol?: number;
  lastTs?: number;
  flash?: "up" | "down";
};

const WS_URL =
  import.meta.env.VITE_MASSIVE_WS_URL || "ws://localhost:9000/ws";
const STORAGE_KEY = "massive-live:tickers";
const PRESETS = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY", "AMZN", "META", "GOOG"];

function fmtPrice(n?: number) {
  if (n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, {
    maximumFractionDigits: n < 10 ? 4 : 2,
    minimumFractionDigits: 2,
  });
}
function fmtInt(n?: number) {
  if (n === undefined) return "—";
  return Math.round(n).toLocaleString();
}
function fmtTime(ts?: number) {
  if (!ts) return "—";
  // Massive timestamps come in s, ms, or ns — pick by magnitude
  const ms = ts > 1e15 ? ts / 1e6 : ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleTimeString();
}

const MassiveLive: React.FC = () => {
  const [status, setStatus] = useState<"connecting" | "live" | "disconnected" | "error">(
    "connecting",
  );
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [input, setInput] = useState("");
  const [tickers, setTickers] = useState<Record<string, TickerState>>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const arr = JSON.parse(raw) as string[];
        return Object.fromEntries(arr.map((s) => [s, { sym: s }]));
      }
    } catch {
      /* ignore */
    }
    return {};
  });
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(1000);

  const symbols = useMemo(() => Object.keys(tickers), [tickers]);

  // Persist watchlist
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(symbols));
  }, [symbols]);

  // Subscribe helper
  const send = useCallback((action: "subscribe" | "unsubscribe", syms: string[]) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || syms.length === 0) return;
    ws.send(JSON.stringify({ action, tickers: syms }));
  }, []);

  // Apply incoming Massive event to our state
  const applyEvent = useCallback((e: Record<string, unknown>) => {
    if (e.ev === "error") {
      setStatus("error");
      setStatusMessage(String(e.message ?? "server error"));
      return;
    }
    if (e.ev === "status") return;
    const sym = e.sym as string | undefined;
    if (!sym) return;
    setTickers((prev) => {
      const cur = prev[sym];
      if (!cur) return prev;
      const next: TickerState = { ...cur };
      if (e.ev === "T") {
        const prevPrice = cur.price;
        next.price = Number(e.p);
        next.size = Number(e.s ?? 0);
        next.lastTs = Number(e.t ?? Date.now());
        if (prevPrice !== undefined) {
          next.flash =
            next.price! > prevPrice ? "up" : next.price! < prevPrice ? "down" : undefined;
        }
      } else if (e.ev === "Q") {
        // Massive NBBO: bp/ap or p/P depending on cluster
        next.bid = (e.bp ?? e.p) !== undefined ? Number(e.bp ?? e.p) : next.bid;
        next.ask = (e.ap ?? e.P) !== undefined ? Number(e.ap ?? e.P) : next.ask;
        next.bidSize = (e.bs ?? e.s) !== undefined ? Number(e.bs ?? e.s) : next.bidSize;
        next.askSize = (e.as ?? e.S) !== undefined ? Number(e.as ?? e.S) : next.askSize;
      } else if (e.ev === "AM") {
        next.dayOpen = e.op !== undefined ? Number(e.op) : next.dayOpen;
        next.dayHigh =
          e.h !== undefined ? Math.max(Number(e.h), next.dayHigh ?? -Infinity) : next.dayHigh;
        next.dayLow =
          e.l !== undefined ? Math.min(Number(e.l), next.dayLow ?? Infinity) : next.dayLow;
        next.dayVol = e.av !== undefined ? Number(e.av) : next.dayVol;
      }
      return { ...prev, [sym]: next };
    });
    if (e.ev === "T") {
      // clear flash after 600ms so the border returns to neutral
      window.setTimeout(() => {
        setTickers((prev) => {
          const cur = prev[sym!];
          if (!cur || !cur.flash) return prev;
          return { ...prev, [sym!]: { ...cur, flash: undefined } };
        });
      }, 600);
    }
  }, []);

  // (re)connect with exponential backoff
  useEffect(() => {
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      setStatus("connecting");
      setStatusMessage("");
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.addEventListener("open", () => {
        backoffRef.current = 1000;
        setStatus("live");
        setStatusMessage("");
        if (symbols.length > 0) {
          ws.send(JSON.stringify({ action: "subscribe", tickers: symbols }));
        }
      });

      ws.addEventListener("message", (ev) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (!Array.isArray(parsed)) return;
        for (const e of parsed) {
          if (e && typeof e === "object") applyEvent(e as Record<string, unknown>);
        }
      });

      ws.addEventListener("close", () => {
        if (stopped) return;
        setStatus("disconnected");
        setStatusMessage(
          `disconnected · retrying in ${Math.round(backoffRef.current / 1000)}s`,
        );
        const delay = backoffRef.current;
        backoffRef.current = Math.min(backoffRef.current * 2, 30000);
        window.setTimeout(connect, delay);
      });

      ws.addEventListener("error", () => {
        setStatus("error");
        setStatusMessage("error connecting to bridge");
      });
    };

    connect();
    return () => {
      stopped = true;
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applyEvent]);

  const addTicker = (raw: string) => {
    const sym = raw.trim().toUpperCase();
    if (!sym || tickers[sym]) return;
    setTickers((prev) => ({ ...prev, [sym]: { sym } }));
    send("subscribe", [sym]);
  };
  const removeTicker = (sym: string) => {
    setTickers((prev) => {
      const next = { ...prev };
      delete next[sym];
      return next;
    });
    send("unsubscribe", [sym]);
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Activity className="w-6 h-6 text-emerald-400" />
        <h1 className="text-2xl font-semibold text-white">Massive Live</h1>
        <span
          className={`ml-2 inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-full border ${
            status === "live"
              ? "border-emerald-500/40 text-emerald-400 bg-emerald-500/10"
              : status === "connecting"
                ? "border-yellow-500/40 text-yellow-300 bg-yellow-500/10"
                : "border-red-500/40 text-red-400 bg-red-500/10"
          }`}
        >
          {status === "live" ? (
            <Wifi className="w-3.5 h-3.5" />
          ) : (
            <WifiOff className="w-3.5 h-3.5" />
          )}
          {status === "live" ? "live" : statusMessage || status}
        </span>
        <span className="ml-auto text-xs text-gray-500 font-mono">
          {WS_URL}
        </span>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          addTicker(input);
          setInput("");
        }}
        className="flex flex-wrap gap-2 items-center"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Add ticker (e.g. AAPL)"
          className="px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white placeholder:text-gray-500 focus:outline-none focus:border-emerald-500/50 w-56"
          autoComplete="off"
        />
        <button
          type="submit"
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-white font-medium transition"
        >
          <Plus className="w-4 h-4" /> Add
        </button>
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => addTicker(p)}
            disabled={!!tickers[p]}
            className="px-2.5 py-1.5 rounded-md text-xs border border-white/10 text-gray-300 hover:border-white/30 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition"
          >
            {p}
          </button>
        ))}
      </form>

      {symbols.length === 0 ? (
        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-12 text-center text-gray-400">
          No tickers yet — add one above to start streaming.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          <AnimatePresence>
            {symbols.map((sym) => {
              const s = tickers[sym];
              const change =
                s.price !== undefined && s.dayOpen ? s.price - s.dayOpen : undefined;
              const changePct =
                change !== undefined && s.dayOpen ? (change / s.dayOpen) * 100 : undefined;
              const dir =
                change === undefined ? "" : change >= 0 ? "text-emerald-400" : "text-red-400";
              const arrow = change === undefined ? "" : change >= 0 ? "▲" : "▼";
              const flashClass =
                s.flash === "up"
                  ? "border-emerald-500/60"
                  : s.flash === "down"
                    ? "border-red-500/60"
                    : "border-white/10";
              return (
                <motion.div
                  key={sym}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.18 }}
                  className={`rounded-xl border bg-gray-900/60 backdrop-blur p-4 transition-colors ${flashClass}`}
                >
                  <div className="flex items-baseline justify-between mb-1.5">
                    <div className="text-xl font-bold tracking-wide text-white">{sym}</div>
                    <button
                      onClick={() => removeTicker(sym)}
                      className="text-gray-500 hover:text-red-400 transition"
                      aria-label="Remove"
                    >
                      <XIcon className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="text-3xl font-semibold text-white tabular-nums">
                    ${fmtPrice(s.price)}
                  </div>
                  <div className={`text-sm ${dir} tabular-nums`}>
                    {arrow} {change === undefined ? "—" : fmtPrice(change)} (
                    {changePct === undefined ? "—" : fmtPrice(changePct)}%)
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-3 text-xs text-gray-300">
                    <div className="flex justify-between">
                      <span className="text-gray-500">Bid</span>
                      <span className="tabular-nums">
                        {fmtPrice(s.bid)} × {fmtInt(s.bidSize)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Ask</span>
                      <span className="tabular-nums">
                        {fmtPrice(s.ask)} × {fmtInt(s.askSize)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Day O</span>
                      <span className="tabular-nums">{fmtPrice(s.dayOpen)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Day H</span>
                      <span className="tabular-nums">{fmtPrice(s.dayHigh)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Day L</span>
                      <span className="tabular-nums">{fmtPrice(s.dayLow)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Vol</span>
                      <span className="tabular-nums">{fmtInt(s.dayVol)}</span>
                    </div>
                    <div className="col-span-2 flex justify-between">
                      <span className="text-gray-500">Last trade</span>
                      <span className="text-gray-400 tabular-nums">
                        {fmtTime(s.lastTs)}
                      </span>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
};

export default MassiveLive;
