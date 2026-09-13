/// Single source of truth for whether each service talks to mocked or live
/// data — no screen code should ever check these directly.
///
/// Split per-service (rather than one flag) because they go live on
/// different schedules. Plan and AgentChat use the FastAPI backend, while
/// Session, Plan, and AgentChat use FastAPI. Location uses the device GPS, and
/// Perception uses the live camera pipeline on Android/iOS with a web fallback.
const bool useMockPlan = false;
const bool useMockAgentChat = false;
const bool useMockSession = false;
const bool useMockPerception = false;
const bool useMockLocation = false;
