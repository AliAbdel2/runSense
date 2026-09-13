/// Base URL for the FastAPI backend (see app/ at the repo root).
///
/// 10.0.2.2 is the Android emulator's special alias for the host machine's
/// localhost — plain "localhost" from inside the emulator points at the
/// emulator itself, not the machine running `docker compose up`. Swap this
/// when the backend moves off localhost (see app_config.dart's note on the
/// agent eventually running on a server).
const String apiBaseUrl = String.fromEnvironment(
  'RUNSENSE_API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

/// Must match RUNSENSE_API_KEY in the backend's root .env file.
const String apiKey = String.fromEnvironment('RUNSENSE_API_KEY');

Map<String, String> apiJsonHeaders() => {
      'Content-Type': 'application/json',
      if (apiKey.isNotEmpty) 'Authorization': 'Bearer $apiKey',
    };
