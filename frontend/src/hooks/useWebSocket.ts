import { useEffect, useRef, useState } from "react";
import type { PipelineFrame } from "../lib/types";

type Status = "connecting" | "open" | "closed";

// Subscribes to the backend /ws stream, auto-reconnects, and hands each
// pipeline frame to the caller. The web layer stays dumb: no logic here beyond
// transport + reconnect.
export function useWebSocket(onFrame: (f: PipelineFrame) => void) {
  const [status, setStatus] = useState<Status>("connecting");
  const ref = useRef<WebSocket | null>(null);
  const cb = useRef(onFrame);
  cb.current = onFrame;

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws`);
      ref.current = ws;
      setStatus("connecting");
      ws.onopen = () => setStatus("open");
      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === "pipeline_event") cb.current(data as PipelineFrame);
      };
      ws.onclose = () => {
        setStatus("closed");
        if (!closed) retry = setTimeout(connect, 1500);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      ref.current?.close();
    };
  }, []);

  return status;
}
