/// Base URL for the FastAPI backend (see app/ at the repo root).
///
/// 10.0.2.2 is the Android emulator's special alias for the host machine's
/// localhost — plain "localhost" from inside the emulator points at the
/// emulator itself, not the machine running `docker compose up`. Swap this
/// when the backend moves off localhost (see app_config.dart's note on the
/// agent eventually running on a server).
const String apiBaseUrl = 'http://10.0.2.2:8000';
