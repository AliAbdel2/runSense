import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:runsense/main.dart';

void main() {
  // Without this, every flutter_tts platform-channel call (speak/stop/...)
  // throws MissingPluginException, which silently aborts whichever async
  // handler awaited it (e.g. HomeScreen._startSession never reaches its
  // Navigator.push after `await tts.speak(...)` throws) — no test failure
  // is raised at the throw site, so the symptom shows up several steps
  // later as "widget not found" and looks unrelated to TTS entirely.
  TestWidgetsFlutterBinding.ensureInitialized();
  const ttsChannel = MethodChannel('flutter_tts');
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(ttsChannel, (call) async => null);

  testWidgets('Home screen shows RunSense title', (WidgetTester tester) async {
    await tester.pumpWidget(const RunSenseApp(forceMocks: true));
    await tester.pump(const Duration(milliseconds: 350)); // mocked getWeekPlan() delay

    expect(find.text('RunSense'), findsOneWidget);
  });

  testWidgets(
      'Start Session -> coach briefing -> Start Run -> scripted alerts -> '
      'End Session shows the real alert count on the summary screen',
      (WidgetTester tester) async {
    // bySemanticsLabel needs a live semantics tree. Disposed explicitly at
    // the end of this test body, not via addTearDown: flutter_test's
    // end-of-test SemanticsHandle check runs before package:test's own
    // tearDown queue, so an addTearDown-scheduled dispose is too late.
    final semanticsHandle = tester.ensureSemantics();

    // forceMocks: true is required here — RunSenseApp otherwise wires the
    // real camera-backed PerceptionService (useLiveCamera in app_config.dart),
    // which would try to open an actual camera under test.
    await tester.pumpWidget(const RunSenseApp(forceMocks: true));
    await tester.pump(const Duration(milliseconds: 350)); // getWeekPlan() delay

    await tester.tap(find.text('START SESSION'));
    await tester.pump(); // rebuild into CoachBriefingScreen
    await tester.pump(const Duration(milliseconds: 450)); // mocked coach reply delay

    expect(find.text('Coach Briefing'), findsOneWidget);

    await tester.tap(find.text('START RUN'));
    await tester.pump(); // rebuild after tap
    // Camera permission and Wakelock both have no platform channel under
    // test, so each waits out its own 5s timeout before proceeding as if
    // denied/unavailable — see coach_briefing_screen.dart's _startRun and
    // live_run_screen.dart's _start.
    await tester.pump(const Duration(seconds: 5)); // camera permission timeout
    await tester.pump(const Duration(seconds: 5)); // wakelock enable timeout
    await tester.pump(const Duration(milliseconds: 350)); // startSession() delay

    expect(find.text('Live Run'), findsOneWidget);

    // MockData.alertScript fires NOTICE/WARNING/DANGER at t+2s/t+6s/t+9s —
    // a single bounded pump (not pumpAndSettle) because MockLocationService's
    // Timer.periodic keeps ticking every second until End Session stops it,
    // which would make pumpAndSettle spin forever waiting for a steady state
    // that never arrives.
    await tester.pump(const Duration(seconds: 10));

    // _RunStat wraps each stat in Semantics(label: '$label $value').
    expect(find.bySemanticsLabel(RegExp(r'^alerts 3$')), findsOneWidget);

    await tester.tap(find.text('END SESSION'));
    await tester.pump(); // rebuild into the _ending state
    // Wakelock disable also has no platform channel under test, so it waits
    // out its own 5s timeout — see _endSession in live_run_screen.dart.
    await tester.pump(const Duration(seconds: 5)); // wakelock disable timeout
    // Not pumpAndSettle for this step: it stops as soon as one 100ms step
    // produces no new frame, which can happen well before the mocked 500ms
    // endSession() delay's Future actually fires — it isn't guaranteed to
    // keep advancing through a quiet gap toward a still-pending Timer.
    await tester.pump(const Duration(milliseconds: 700));
    // stopSimulation()/stopTracking() already ran synchronously at the top
    // of _endSession(), so the periodic location timer is already
    // cancelled — safe to settle the page-route transition from here.
    await tester.pumpAndSettle();

    expect(find.text('Session Summary'), findsOneWidget);
    // _StatRow (summary screen) wraps each row in Semantics(label: '$label: $value').
    expect(find.bySemanticsLabel(RegExp(r'^Alerts: 3$')), findsOneWidget);

    semanticsHandle.dispose();
  });
}
