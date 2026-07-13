/**
 * Shared configuration constants for the Electron app.
 * Single source of truth for ports and URLs.
 */

export const BACKEND_PORT = 8000;
export const BACKEND_FALLBACK_PORT_START = 18000;
export const BACKEND_FALLBACK_PORT_RANGE = 20;
export const FRONTEND_DEV_PORT = 5173;
export const LOCALHOST_HOST = '127.0.0.1';

export const FRONTEND_DEV_URL = `http://${LOCALHOST_HOST}:${FRONTEND_DEV_PORT}`;
