import 'package:flutter/material.dart';
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
    await tester.pumpWidget(const RunSenseApp());
    await tester.pump(const Duration(milliseconds: 350)); // mocked getWeekPlan() delay

    expect(find.text('RunSense'), findsOneWidget);
  });

  testWidgets(
      'Start Session -> scripted alerts -> End Session shows the real alert '
      'count on the summary screen', (WidgetTester tester) async {
    // bySemanticsLabel needs a live semantics tree. Disposed explicitly at
    // the end of this test body, not via addTearDown: flutter_test's
    // end-of-test SemanticsHandle check runs before package:test's own
    // tearDown queue, so an addTearDown-scheduled dispose is too late.
    final semanticsHandle = tester.ensureSemantics();

    await tester.pumpWidget(const RunSenseApp());
    await tester.pump(const Duration(milliseconds: 350)); // getWeekPlan() delay

    await tester.tap(find.text('START SESSION'));
    await tester.pump(); // rebuild after tap
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
    await tester.pump();
    print('after tap+pump exception=${tester.takeException()}');
    await tester.pump(const Duration(milliseconds: 700));
    print('after 700ms pump exception=${tester.takeException()}');
    print(tester.allWidgets.whereType<Text>().map((t) => t.data).toList());
    await tester.pumpAndSettle();
    print('after pumpAndSettle exception=${tester.takeException()}');

    expect(find.text('Session Summary'), findsOneWidget);
    // _StatRow (summary screen) wraps each row in Semantics(label: '$label: $value').
    expect(find.bySemanticsLabel(RegExp(r'^Alerts: 3$')), findsOneWidget);
  });
}
