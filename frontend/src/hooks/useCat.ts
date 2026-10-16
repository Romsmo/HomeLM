import { useCallback, useEffect, useReducer, useRef } from "react";
import { ReconnectingSocket } from "../lib/socket";
import type { ClientEvent } from "../protocol";
import { initialState, reducer } from "../state/store";

function socketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws`;
}

/** Verbindet den Browser mit Cat und hält den Zustand aktuell. */
export function useCat(onUnreachable: () => void) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const socketRef = useRef<ReconnectingSocket | null>(null);
  const unreachableRef = useRef(onUnreachable);
  unreachableRef.current = onUnreachable;

  useEffect(() => {
    const socket = new ReconnectingSocket({
      url: socketUrl(),
      onEvent: (event) => dispatch({ kind: "server", event }),
      onStatus: (status) => dispatch({ kind: "connection", status }),
      onUnreachable: () => unreachableRef.current(),
    });
    socketRef.current = socket;
    socket.start();
    return () => {
      socket.stop();
      socketRef.current = null;
    };
  }, []);

  const send = useCallback((event: ClientEvent) => socketRef.current?.send(event) ?? false, []);
  return { state, dispatch, send };
}
