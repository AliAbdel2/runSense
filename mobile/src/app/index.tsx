import { useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ExpoSpeechRecognitionModule, useSpeechRecognitionEvent } from 'expo-speech-recognition';
import * as Speech from 'expo-speech';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { API_BASE_URL } from '@/api/config';
import { askCoach } from '@/api/client';
import { ActionButton } from '@/components/ActionButton';
import { useAnnounce, useAnnounceOnce } from '@/hooks/useAnnounce';
import { usePlan } from '@/hooks/usePlan';
import { formatKm, humanStatus, nextSession, sessionLabel, sessionSentence, todayAnnouncement } from '@/lib/format';
import { colors, fontSize, radius, spacing } from '@/lib/theme';

/**
 * Home / Today.
 *
 * Speaks today's session as soon as it loads, then offers exactly one large
 * primary action. Reading order is deliberate and matches the spoken order:
 * the session sentence, the primary button, then the secondary actions.
 */
export default function TodayScreen() {
  const router = useRouter();
  const announce = useAnnounce();
  const { run, loading, error, reload } = usePlan();
  const [coachNotice, setCoachNotice] = useState<string | null>(null);
  const [question, setQuestion] = useState<string | null>(null);
  useSpeechRecognitionEvent('result', (event) => { if (event.isFinal) setQuestion(event.results[0]?.transcript ?? null); });
  useSpeechRecognitionEvent('error', (event) => setCoachNotice(`Coach listening failed: ${event.message}`));
  useEffect(() => {
    if (!question) return;
    void askCoach(question).then(({ answer }) => { setCoachNotice(answer); Speech.speak(answer, { language: 'en-US' }); }).catch((error: unknown) => setCoachNotice(error instanceof Error ? error.message : String(error)));
  }, [question]);

  const plan = run?.plan ?? null;
  const session = useMemo(() => nextSession(plan), [plan]);

  // The one auto-announcement this screen makes. Errors are announced too:
  // silence is the worst possible failure mode on a voice-first screen.
  const announcement = useMemo(() => {
    if (loading) return null;
    if (error) return `RunSense could not load your plan. ${error}`;
    return todayAnnouncement(plan, session);
  }, [error, loading, plan, session]);
  useAnnounceOnce(announcement);

  const onStart = useCallback(() => {
    announce('Starting session. Opening the live run screen.');
    router.push('/live');
  }, [announce, router]);

  /**
   * "Ask coach" uses OS/on-device speech recognition, then the separate
   * free-form coach route. The network is only needed for the answer; the
   * question transcription itself remains on device.
   */
  const onAskCoachStart = useCallback(async () => {
    const permission = await ExpoSpeechRecognitionModule.requestPermissionsAsync();
    if (!permission.granted) { const notice = 'Microphone or speech permission was not granted.'; setCoachNotice(notice); announce(notice); return; }
    setCoachNotice('Listening. Hold the button while you ask your coach.');
    ExpoSpeechRecognitionModule.start({ lang: 'en-US', interimResults: false, maxAlternatives: 1, continuous: false, requiresOnDeviceRecognition: true, addsPunctuation: true });
  }, [announce]);
  const onAskCoachStop = useCallback(() => { ExpoSpeechRecognitionModule.stop(); }, []);

  const onOpenWeek = useCallback(() => {
    router.push('/week');
  }, [router]);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      accessibilityLabel="Today's session"
    >
      <View accessible accessibilityRole="header">
        <Text style={styles.heading} maxFontSizeMultiplier={2}>
          Today
        </Text>
      </View>

      {loading ? (
        <Text style={styles.lead} accessibilityLiveRegion="polite" maxFontSizeMultiplier={2}>
          Loading your session…
        </Text>
      ) : null}

      {error ? (
        <View style={styles.errorCard} accessible accessibilityRole="alert">
          <Text style={styles.errorTitle} maxFontSizeMultiplier={2}>
            Plan unavailable
          </Text>
          <Text style={styles.body} maxFontSizeMultiplier={2}>
            {error}
          </Text>
          <Text style={styles.bodyMuted} maxFontSizeMultiplier={2}>
            RunSense is set to {API_BASE_URL}.
          </Text>
        </View>
      ) : null}

      {session && plan ? (
        // One accessible block: the screen reader reads the whole session as a
        // single sentence, exactly as it was announced on open, instead of
        // stopping on each visual line.
        <View
          style={styles.sessionCard}
          accessible
          accessibilityLabel={sessionSentence(session)}
        >
          <Text style={styles.sessionKind} maxFontSizeMultiplier={2}>
            {sessionLabel(session)}
          </Text>
          <Text style={styles.sessionDistance} maxFontSizeMultiplier={2}>
            {session.kind === 'rest' ? 'No running planned' : formatKm(session.km)}
          </Text>
          <Text style={styles.lead} maxFontSizeMultiplier={2}>
            {session.spoken_summary}
          </Text>
          {/* Guide state is text first. The border colour below is decoration
              on top of a word, never the only carrier of the state. */}
          <Text style={styles.body} maxFontSizeMultiplier={2}>
            Venue: {session.venue}
          </Text>
          <Text style={styles.body} maxFontSizeMultiplier={2}>
            Guide: {humanStatus(session.guide_status)}
          </Text>
          <Text style={styles.bodyMuted} maxFontSizeMultiplier={2}>
            Why: {session.rationale}
          </Text>
        </View>
      ) : null}

      <ActionButton
        label="Start session"
        caption={session ? sessionLabel(session) : undefined}
        onPress={onStart}
        accessibilityHint="Opens the live run screen, where audio alerts would run."
        disabled={loading}
      />

      <ActionButton
        label="Ask coach"
        caption="Hold to talk — on-device speech recognition"
        variant="secondary"
        onPress={() => undefined}
        onPressIn={onAskCoachStart}
        onPressOut={onAskCoachStop}
        accessibilityHint="Press and hold while asking a question. Speech recognition runs on the device."
      />

      {coachNotice ? (
        <Text style={styles.notice} accessibilityLiveRegion="polite" maxFontSizeMultiplier={2}>
          {coachNotice}
        </Text>
      ) : null}

      <ActionButton label="Week plan" variant="secondary" onPress={onOpenWeek} />

      {error ? <ActionButton label="Try again" variant="secondary" onPress={reload} /> : null}

      {plan ? (
        <Text style={styles.footer} maxFontSizeMultiplier={2}>
          {`Week of ${plan.week_start}. ${formatKm(plan.week_km)} planned against a ${formatKm(
            plan.baseline_km,
          )} recent weekly baseline. Source: ${run?.mode ?? 'demo'} data, ${run?.planner ?? 'deterministic'} planner.`}
        </Text>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl },
  heading: { color: colors.text, fontSize: fontSize.title, fontWeight: '800' },
  lead: { color: colors.text, fontSize: fontSize.lead },
  body: { color: colors.text, fontSize: fontSize.body },
  bodyMuted: { color: colors.textMuted, fontSize: fontSize.body },
  sessionCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  sessionKind: { color: colors.text, fontSize: fontSize.display, fontWeight: '800' },
  sessionDistance: { color: colors.text, fontSize: fontSize.lead, fontWeight: '600' },
  errorCard: {
    backgroundColor: colors.surfaceMuted,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.danger,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  errorTitle: { color: colors.text, fontSize: fontSize.lead, fontWeight: '700' },
  notice: { color: colors.attention, fontSize: fontSize.body },
  footer: { color: colors.textMuted, fontSize: fontSize.body, marginTop: spacing.sm },
});
