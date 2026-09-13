/// Single source of truth for whether the app talks to mocked or live services.
///
/// Flip this to `false` once teammates' Live*Service implementations are wired
/// into the Provider setup in main.dart — no screen code should ever check
/// this directly.
const bool useMock = true;

/// Perception only. Everything else still honours [useMock].
/// Falls back to the mock wherever the camera module isn't supported (web).
const bool useLiveCamera = true;
