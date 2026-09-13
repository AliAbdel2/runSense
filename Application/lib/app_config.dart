/// Single source of truth for whether each service talks to mocked or live
/// data — no screen code should ever check these directly.
///
/// Plan, AgentChat, and Session use FastAPI. Location uses the device GPS, and
/// Perception uses the live camera pipeline on Android/iOS with a web fallback.
const bool useMockPlan = false;
const bool useMockAgentChat = false;
const bool useMockSession = false;
const bool useMockPerception = false;
const bool useMockLocation = false;
