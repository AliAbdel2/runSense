import Constants from 'expo-constants';

/**
 * Where the RunSense FastAPI server lives.
 *
 * Resolution order (first non-empty wins):
 *   1. `EXPO_PUBLIC_RUNSENSE_API` in the environment (`.env` / shell export).
 *   2. `expo.extra.runsenseApiBaseUrl` in `app.json`.
 *   3. `http://127.0.0.1:8000`, the loopback default from the repo README.
 *
 * A simulator can reach `127.0.0.1`; a physical phone cannot. For a real device
 * the README's existing LAN instructions apply verbatim — the server must be
 * started with its LAN IP in `RUNSENSE_ALLOWED_HOSTS` and bound to all
 * interfaces, because `TrustedHostMiddleware` rejects any other Host header:
 *
 *   export RUNSENSE_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.23
 *   .venv/bin/python -m uvicorn runsense.main:app --host 0.0.0.0 --port 8000
 *
 * then point this app at the same address:
 *
 *   export EXPO_PUBLIC_RUNSENSE_API=http://192.168.1.23:8000
 *
 * Note the server also refuses cross-origin requests (`main.py:local_access`).
 * React Native's fetch sends no `Origin` header, so native builds are fine;
 * `npx expo start --web` served from a different port is not, and needs the
 * dashboard's own origin instead.
 */
function resolveBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_RUNSENSE_API;
  if (typeof fromEnv === 'string' && fromEnv.trim().length > 0) {
    return fromEnv.trim().replace(/\/+$/, '');
  }
  const extra = Constants.expoConfig?.extra as Record<string, unknown> | undefined;
  const fromConfig = extra?.['runsenseApiBaseUrl'];
  if (typeof fromConfig === 'string' && fromConfig.trim().length > 0) {
    return fromConfig.trim().replace(/\/+$/, '');
  }
  return 'http://127.0.0.1:8000';
}

export const API_BASE_URL = resolveBaseUrl();

/** Requests are aborted after this long so a wrong LAN IP fails loudly, not silently. */
export const REQUEST_TIMEOUT_MS = 10_000;
