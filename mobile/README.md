# RunSense mobile (Expo + TypeScript)

A voice-first scaffold of the three screens in the hackathon plan's §9: **Today**,
**Live run**, **Week plan**. It talks to the existing FastAPI backend in this
repository; it does not duplicate any planning logic.

**Read the [Known limitations](#known-limitations) before you believe anything
about this app.** It has been type-checked and nothing more.

## Setup

```sh
cd mobile
npm install
npx expo start
```

Then press `i` (iOS simulator), `a` (Android emulator), `w` (web), or scan the QR
code with Expo Go.

Type-check, the only check this scaffold has actually passed:

```sh
npm run typecheck        # tsc --noEmit
```

## Pointing the app at the backend

Start the API as the root [`README.md`](../README.md) describes:

```sh
.venv/bin/python -m uvicorn runsense.main:app --host 127.0.0.1 --port 8000
```

The base URL resolves in this order (`src/api/config.ts`):

1. `EXPO_PUBLIC_RUNSENSE_API` from the environment
2. `expo.extra.runsenseApiBaseUrl` in `app.json`
3. `http://127.0.0.1:8000`

A simulator on the same machine can reach `127.0.0.1`. **A physical phone
cannot.** For a real device, use the LAN convention the root README already
documents — the server's `TrustedHostMiddleware` rejects any Host it was not
told about, so the LAN IP must be listed explicitly:

```sh
# on the machine running RunSense
export RUNSENSE_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.23
.venv/bin/python -m uvicorn runsense.main:app --host 0.0.0.0 --port 8000

# in this directory, before `npx expo start`
export EXPO_PUBLIC_RUNSENSE_API=http://192.168.1.23:8000
```

Replace `192.168.1.23` with the machine's actual LAN address. Note the backend
also refuses cross-origin requests: React Native's `fetch` sends no `Origin`
header so native builds are fine, but `npx expo start --web` served from a
different port will be blocked by design.

## Layout

```
mobile/
├── app.json                         Expo config: app name "RunSense", camera/mic
│                                    usage strings, expo-router plugin
├── package.json                     Expo SDK 57, React Native 0.86, RN Web
├── tsconfig.json                    extends expo/tsconfig.base, strict + extras
├── expo-env.d.ts                    committed so a fresh clone type-checks
└── src/
    ├── app/                         Expo Router file-based routes
    │   ├── _layout.tsx              Stack navigator (Today → Live run / Week plan)
    │   ├── index.tsx                "/"      Home / Today
    │   ├── live.tsx                 "/live"  Live run (debug view)
    │   └── week.tsx                 "/week"  Week plan
    ├── api/
    │   ├── types.ts                 TS mirrors of runsense/models.py + envelopes
    │   ├── client.ts                typed fetch wrapper over the FastAPI routes
    │   └── config.ts                base-URL resolution (see above)
    ├── components/
    │   └── ActionButton.tsx         the one button type: 64px, role, label, haptic
    ├── hooks/
    │   ├── usePlan.ts               GET /api/demo → RunResult
    │   ├── useAnnounce.ts           AccessibilityInfo.announceForAccessibility
    │   └── usePerceptionStream.ts   the camera seam — permanently disabled today
    └── lib/
        ├── format.ts                wording ported from runsense/static/app.js
        └── theme.ts                 tokens, incl. the 64px touch-target constant
```

## Navigation: Expo Router

File-based routing via `expo-router`, in a single stack. Reasons:

- It is the default for new Expo apps (the official `create-expo-app` template
  ships it), so the scaffold matches what the docs and the tooling assume.
- Deep links come for free, which matters for a later "open today's session"
  notification or a `runsense://` handoff from the web dashboard.
- A **stack**, not tabs, because the three screens are a sequence rather than
  peers: the app opens on Today and speaks; Live run is entered by the one
  primary action; Week plan is a detour. A stack also gives every screen a real
  back affordance that both screen readers already announce correctly.

## Accessibility

The plan's §9 requirements, and where each one lives:

| Requirement | Implementation |
|---|---|
| Auto-announce on open | `useAnnounceOnce` → `AccessibilityInfo.announceForAccessibility`, guarded against repeats, with a short delay so it does not collide with the navigator's own focus announcement |
| One large primary action | `ActionButton` with `variant="primary"`; one per screen |
| 64px touch targets | `TOUCH_TARGET = 64` in `src/lib/theme.ts`, applied as `minWidth`/`minHeight` on every pressable |
| Roles and labels | `accessibilityRole` + `accessibilityLabel` on every interactive element; `accessibilityHint` only where it adds information the label does not |
| Haptic confirmation | `expo-haptics` `impactAsync` on every button press, heavy for primary |
| No colour-only state | Guide status, stream status and busy state are always words first; colour is layered on top of text, never instead of it |
| One sentence per row | `sessionSentence()` in `src/lib/format.ts`; each week row is a single accessible element |
| Screen-reader order = spoken order | Week rows render Monday→Sunday in plan order; Today reads session, then primary action, then secondary |
| Long-press to change a session | `onLongPress` on the row **plus** an explicit "Change session" button, because a long-press is effectively undiscoverable through a screen reader alone |

All of this is written to the correct APIs. **None of it has been verified with
an actual screen reader** — see below.

## How the API types map to the Python models

`src/api/types.ts` is a hand-translation of `runsense/models.py`. Python `date`
becomes an ISO `YYYY-MM-DD` string because the routes return
`model_dump(mode="json")`; `Literal[...]` becomes a TS union.

| Python | TypeScript |
|---|---|
| `models.Activity` | `Activity` |
| `models.Session` | `Session` |
| `models.Plan` | `Plan` (`sessions` is always 7 entries, Monday first) |
| `models.PlanRequest` | `PlanRequest` (all fields optional; the model is `extra="forbid"`) |
| `models.CommitRequest` | `CommitRequest` |
| `Literal["easy","intervals","long","rest"]` | `SessionKind` |
| `Literal["treadmill","track","park","home"]` | `Venue` |
| `Literal["accepted","pending","declined","not_required"]` | `GuideStatus` |
| `Literal["athlete_authored","synthetic","strava_mcp"]` | `ActivitySource` |
| `Literal["baseline","guide_cancelled","missed_session","calendar_retry"]` | `Scenario` |
| `planner.validate_plan(...)` return | `Validation` / `ValidationCheck` |
| agent trace dicts | `TraceStep` (`status` stays a string — the server's is free-form) |
| `agent.Agent.plan(...)` / `Agent.public(...)` result | `RunResult` |
| `triage.AlertEvent.to_dict()` | `PerceptionAlert` (nothing produces one yet) |

## Known limitations

Read this as the status of the scaffold, not a to-do list of small gaps.

- **Native runtime unverified.** The app and native modules have been type-checked
  and Jest covers the ported triage logic, but this environment has no Xcode,
  simulator, Android SDK, emulator, phone, microphone or camera. It has not been
  built or run on a device, simulator, emulator, Expo Go, or the web target.
- **No screen-reader testing.** The TalkBack/VoiceOver behaviour is written to
  the documented APIs and the documented semantics, but no announcement, focus
  order, or gesture has been heard or observed. The accessibility table above
  describes intent and code, not measured behaviour.
- **Ask coach is wired but unverified.** Press-and-hold uses the OS speech
  recognizer with `requiresOnDeviceRecognition`, then calls `/api/coach/ask` and
  speaks the returned answer locally. Native permission, transcription, network
  round trip and playback still need a development build and device test.
- **On-device perception is wired but unverified.** `usePerceptionStream` uses
  VisionCamera, the resize plugin, bundled TFLite output decoding, and the
  TypeScript triage state machine. `mobile/assets/models/yolo11n.tflite` must be
  generated first; no model file exists yet, and camera/model inference has not
  run on a device or simulator.
- **Change session is recorded, not replanned.** The mobile client posts a
  free-text request to `/api/sessions/{session_id}/change-request`; the backend
  records a trace and acknowledges it. It intentionally does not re-plan.
- **Earcons are generated and wired but unverified.** Stereo WAV assets are
  generated by `scripts/generate_earcons.py` and selected by tier; playback and
  audibility still need native testing.
- **No Strava personal previews.** Those routes require the `runsense_personal`
  cookie that the web dashboard gets from `GET /`; this app does not hold one.
  The client functions exist and are typed, but will 401 from the phone.
- **Demo data only.** The screens read `GET /api/demo`, which is synthetic. Live
  mode needs `RUNSENSE_ADMIN_TOKEN` bearer auth, which the client supports as a
  parameter but no screen supplies.
- **Tests are unit-only.** `npm test` runs the four self-contained triage tests;
  no native integration, camera, model, microphone, screen-reader, or audio
  playback test exists yet.
