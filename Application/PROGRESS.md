# PROGRESS

## Environment setup (pre-checkpoint 1)
- Flutter SDK not previously installed on this machine. Installed stable channel via `git clone` into `C:\flutter`, added to user PATH permanently.
- Run target chosen: **Chrome/web only** for this hackathon (no Android SDK/emulator installed — `flutter doctor` shows Android toolchain and Visual Studio (Windows desktop) as missing/red, this is expected and not needed).
- Project created at `Application/` (repo root has a stale, unrelated React Native/Expo scaffold under `mobile/` from before the pivot to Flutter — left untouched, not part of this app).
- Verified `flutter build web --release` succeeds end-to-end.
- Saved both planning docs into this folder: `runsense_flutter_plan.md` (this app) and `obstacle_detection_module_plan.md` (Phase 2, camera-based perception — built after this app's mocked skeleton is done). Added a section 10 note to `runsense_flutter_plan.md` cross-referencing how the obstacle-detection module will eventually become `LivePerceptionService`.

## Checkpoint 1 — Scaffold
- Added `provider ^6.1.2`, `flutter_tts ^4.2.0`, `intl ^0.19.0` to `pubspec.yaml`, ran `flutter pub get`.
- Created `lib/app_config.dart` with `useMock = true`.
- Created models exactly as specified in plan section 3:
  - `lib/models/athlete.dart` — `Athlete`
  - `lib/models/guide_status.dart` — `GuideStatus` enum (split out of `session.dart` per the plan's own folder listing in section 2)
  - `lib/models/session.dart` — `SessionType` enum, `PlannedSession`, `CompletedSession`
  - `lib/models/alert.dart` — `AlertTier`, `Zone`, `Distance` enums, `ObstacleAlert`
- Created abstract service interfaces exactly as specified in plan section 4:
  - `lib/services/plan_service.dart` — `PlanService`
  - `lib/services/session_service.dart` — `SessionService`
  - `lib/services/perception_service.dart` — `PerceptionService`
  - `lib/services/agent_chat_service.dart` — `AgentChatService`
- **Deviations from section 2's folder listing (flagged for whoever reads this next):**
  - Did **not** create `models/activity.dart` or `models/plan_week.dart`. Section 3 of the plan gives no code for either, and no interface in section 4 references them (`PlanService.getWeekPlan` returns `List<PlannedSession>` directly, not a wrapper). Skipped rather than inventing speculative fields. Add them in a later checkpoint only if a concrete need shows up (e.g. a `WeekPlan` wrapper if the mock/live plan services end up needing week-level metadata beyond a list).
  - Did **not** create `lib/services/tts_service.dart` yet. It's real (not mocked) per section 4, but the hour-by-hour breakdown (section 7) wires it up alongside the Home screen (hours 2–3.5), so it's deferred to that checkpoint rather than built with nothing to call it yet.
- No mock data, no mock service implementations, no UI/screens built yet — intentionally out of scope for Checkpoint 1.
- `flutter analyze` — no issues.

**Next checkpoint (2):** implement `lib/services/mock/mock_data.dart` (Sara persona) and the four `Mock*Service` classes per section 5.
