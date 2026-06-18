import type { StreamMessage } from "@/lib/types";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "";

export function localWebSocketUrl(path = "/ws") {
  if (typeof window === "undefined") return null;
  if (API.startsWith("http://") || API.startsWith("https://")) {
    const url = new URL(API);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = path;
    url.search = "";
    return url.toString();
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host =
    window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
      ? `${window.location.hostname}:8765`
      : window.location.host;
  return `${protocol}//${host}${path}`;
}

export function subscribeLocalStream<T>(
  topics: string[],
  onMessage: (message: StreamMessage<T>) => void,
) {
  const url = localWebSocketUrl();
  if (!url) return () => {};
  const socket = new WebSocket(url);
  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({ subscribe: topics }));
  });
  socket.addEventListener("message", (event) => {
    try {
      onMessage(JSON.parse(event.data) as StreamMessage<T>);
    } catch {
      // Ignore malformed local stream messages; the REST snapshot remains the fallback.
    }
  });
  return () => {
    socket.close();
  };
}
