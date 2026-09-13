/// Single source of truth for whether each service talks to mocked or live
/// data — no screen code should ever check these directly.
///
/// Split per-service (rather than one flag) because they go live on
/// different schedules: Plan and AgentChat are backed by a real FastAPI
/// endpoint today; Session/Perception/Location are not (Session is entangled
/// with the not-yet-built Perception pipeline in LiveRunScreen, and Location
/// is mid-flight GPS groundwork) — flipping one global flag would make the
/// app throw UnimplementedError on startup the moment any one of those
/// wasn't ready.
const bool useMockPlan = false;
const bool useMockAgentChat = false;
const bool useMockSession = true;
const bool useMockPerception = true;
const bool useMockLocation = true;
