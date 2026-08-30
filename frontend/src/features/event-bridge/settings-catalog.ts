import type { EventBridgeSettings } from "@/features/event-bridge/types";

export const booleanFields: Array<{ key: keyof EventBridgeSettings; label: string; description: string }> = [
  { key: "ENABLED", label: "Abilita", description: "Accetta e inoltra gli eventi del plugin." },
  { key: "WEBSOCKET_ENABLED", label: "WebSocket", description: "Mantiene il canale bidirezionale aperto." },
  { key: "HTTP_FALLBACK_ENABLED", label: "Fallback HTTP", description: "Riceve eventi HTTP quando WebSocket non è disponibile." },
  { key: "CAPTURE_PLAYBACK_EVENTS", label: "Riproduzione", description: "Registra gli eventi della riproduzione." },
  { key: "CAPTURE_SESSION_EVENTS", label: "Sessione", description: "Registra gli eventi di sessione configurati." },
  { key: "CAPTURE_PLUGIN_EVENTS", label: "Plugin", description: "Registra gli eventi tecnici del plugin." },
  { key: "INCLUDE_RAW_PAYLOAD", label: "Dati grezzi", description: "Include il payload tecnico originale." },
];

export const numericFields: Array<{ key: keyof EventBridgeSettings; label: string; minimum: number }> = [
  { key: "EVENT_BATCH_INTERVAL_SECONDS", label: "Intervallo batch (s)", minimum: 0 },
  { key: "WEBSOCKET_RECONNECT_SECONDS", label: "Riconnessione WS (s)", minimum: 1 },
  { key: "HTTP_TIMEOUT_SECONDS", label: "Timeout HTTP", minimum: 1 },
  { key: "RETRY_COUNT", label: "Tentativi HTTP", minimum: 0 },
];

export const eventFields: Array<{ key: keyof EventBridgeSettings; label: string }> = [
  { key: "PLAYBACK_EVENT_NAMES", label: "Eventi di riproduzione" },
  { key: "SESSION_EVENT_NAMES", label: "Eventi sessione" },
  { key: "PLUGIN_EVENT_NAMES", label: "Eventi plugin" },
];
