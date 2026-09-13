/// Single source of truth for whether each service talks to mocked or live
/// data — no screen code should ever check these directly.
///
/// Split per-service (rather than one flag) because they go live on
/// different schedules. Plan and AgentChat use the FastAPI backend, while
/// Session and Location still use their mock implementations. Perception uses
/// the live camera pipeline on Android/iOS and falls back to the mock on web.
const bool useMockPlan = false;
const bool useMockAgentChat = false;
const bool useMockSession = true;
const bool useMockPerception = false;
const bool useMockLocation = true;
