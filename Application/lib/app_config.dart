/// Single source of truth for whether the app talks to mocked or live services.
///
/// Flip this to `false` once teammates' Live*Service implementations are wired
/// into the Provider setup in main.dart — no screen code should ever check
/// this directly.
const bool useMock = true;
