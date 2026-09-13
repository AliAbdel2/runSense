# RunSense Flutter app

The app uses the FastAPI backend for plans, coach chat, and live-session
persistence. GPS and obstacle detection run on the device and GPS samples are
sent to the backend during a session.

Start the backend from the repository root:

```sh
docker compose up --build
```

Copy `env.example.json` to the gitignored `env.json`, fill in values that match
the backend `.env`, then launch an Android emulator build:

```sh
flutter run --dart-define-from-file=env.json
```

The default backend URL is `http://10.0.2.2:8000`, Android Emulator's alias for
the host machine. Use `http://127.0.0.1:8000` for Chrome and an HTTPS/LAN URL for
a physical device.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.
