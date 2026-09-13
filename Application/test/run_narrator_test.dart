import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:runsense/models/alert.dart';
import 'package:runsense/services/run_narrator.dart';
import 'package:runsense/services/tts_service.dart';

/// Overrides the real flutter_tts calls so RunNarrator's priority rules can
/// be verified without a platform channel, and so the test controls
/// `isSpeaking` directly instead of racing flutter_tts's own timing.
class FakeTtsService extends TtsService {
  bool speaking = false;
  int speakCalls = 0;
  int interruptCalls = 0;
  String? lastUtterance;

  @override
  bool get isSpeaking => speaking;

  @override
  Future<void> speak(String text) async {
    speakCalls++;
    lastUtterance = text;
    speaking = true;
  }

  @override
  Future<void> interruptAndSpeak(String text) async {
    interruptCalls++;
    lastUtterance = text;
    speaking = true;
  }

  @override
  Future<void> stop() async {
    speaking = false;
  }
}

ObstacleAlert _alert(AlertTier tier, [String utterance = 'alert']) =>
    ObstacleAlert(
      objectClass: 'person',
      zone: Zone.center,
      distance: Distance.near,
      tier: tier,
      utterance: utterance,
      latencyMs: 0,
      ts: DateTime.now(),
    );

void main() {
  // FakeTtsService's constructor still runs TtsService()'s real flutter_tts
  // setup calls; mock the channel so those don't throw MissingPluginException.
  TestWidgetsFlutterBinding.ensureInitialized();
  const ttsChannel = MethodChannel('flutter_tts');
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(ttsChannel, (call) async => null);

  test('danger obstacle always interrupts, even mid-speech', () {
    final tts = FakeTtsService()..speaking = true;
    final narrator = RunNarrator(tts);

    narrator.announceObstacle(_alert(AlertTier.danger, 'Stop - person ahead'));

    expect(tts.interruptCalls, 1);
    expect(tts.lastUtterance, 'Stop - person ahead');
  });

  test('warning/notice obstacle is skipped while speech is already playing',
      () {
    final tts = FakeTtsService()..speaking = true;
    final narrator = RunNarrator(tts);

    narrator.announceObstacle(_alert(AlertTier.warning, 'Person left'));

    expect(tts.speakCalls, 0);
    expect(tts.interruptCalls, 0);
  });

  test('warning/notice obstacle speaks when the engine is idle', () {
    final tts = FakeTtsService();
    final narrator = RunNarrator(tts);

    narrator.announceObstacle(_alert(AlertTier.notice, 'Bike far right'));

    expect(tts.speakCalls, 1);
  });

  test('pace cue is suppressed while speech is already playing', () {
    final tts = FakeTtsService()..speaking = true;
    final narrator = RunNarrator(tts);

    narrator.announcePace('Pace, five thirty-three per kilometre');

    expect(tts.speakCalls, 0);
  });

  test('pace cue is suppressed inside the quiet window after an obstacle',
      () {
    final tts = FakeTtsService();
    final narrator = RunNarrator(tts);

    narrator.announceObstacle(_alert(AlertTier.notice, 'Bike far right'));
    tts.speaking = false; // the obstacle utterance "finished" already

    narrator.announcePace('Pace, five thirty-three per kilometre');

    // Only the obstacle's own utterance went through; the pace cue was
    // dropped because it landed inside the 3s post-obstacle quiet window.
    expect(tts.speakCalls, 1);
  });

  test('pace cue fires once idle and outside the quiet window', () async {
    final tts = FakeTtsService();
    final narrator = RunNarrator(tts);

    narrator.announceObstacle(_alert(AlertTier.notice, 'Bike far right'));
    tts.speaking = false;
    await Future.delayed(const Duration(milliseconds: 3100));

    narrator.announcePace('Pace, five thirty-three per kilometre');

    expect(tts.speakCalls, 2);
    expect(tts.lastUtterance, 'Pace, five thirty-three per kilometre');
  });
}
