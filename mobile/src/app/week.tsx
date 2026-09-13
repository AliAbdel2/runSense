import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { Session } from '@/api/types';
import { requestSessionChange } from '@/api/client';
import { ActionButton } from '@/components/ActionButton';
import { useAnnounce, useAnnounceOnce } from '@/hooks/useAnnounce';
import { usePlan } from '@/hooks/usePlan';
import { formatKm, guideNeedsAttention, humanStatus, sessionLabel, sessionSentence, weekdayShort } from '@/lib/format';
import { TOUCH_TARGET, colors, fontSize, radius, spacing } from '@/lib/theme';

/**
 * Week plan — a read-only list of the seven sessions.
 *
 * Each row is one accessible element carrying one sentence (`sessionSentence`),
 * so the screen-reader order is the spoken order: Monday through Sunday, one
 * utterance per day, nothing to swipe through inside a row.
 *
 * Changing a session can be reached two ways. Long-press is the gesture the
 * plan asks for, but a long-press is close to undiscoverable through a screen
 * reader alone, so every row also carries an explicit "Change session" button.
 * The button is the accessible path; the long-press is a shortcut on top of it.
 */
export default function WeekPlanScreen() {
  const { run, loading, error, reload } = usePlan();
  const announce = useAnnounce();
  const [pending, setPending] = useState<string | null>(null);

  const plan = run?.plan ?? null;

  useAnnounceOnce(
    loading
      ? null
      : error
        ? `Week plan unavailable. ${error}`
        : plan
          ? `Week plan for ${plan.athlete_name}, seven sessions, ${formatKm(plan.week_km)} total.`
          : null,
  );

  /**
   * "Change session" records an intent for later review. It does not re-plan
   * synchronously or mutate the Calendar event.
   */
  const onRequestChange = useCallback(
    (session: Session) => {
      const message = `Change request recorded for ${sessionLabel(session)} on ${session.date}.`;
      setPending(`${message} Re-planning is not automatic.`);
      announce(message);
      void requestSessionChange(session.id, 'Move or change this session.')
        .catch((error: unknown) => setPending(error instanceof Error ? error.message : String(error)));
    },
    [announce],
  );

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View accessible accessibilityRole="header">
        <Text style={styles.heading} maxFontSizeMultiplier={2}>
          This week
        </Text>
      </View>

      {loading ? (
        <Text style={styles.body} accessibilityLiveRegion="polite" maxFontSizeMultiplier={2}>
          Loading the week…
        </Text>
      ) : null}

      {error ? (
        <View style={styles.errorCard} accessible accessibilityRole="alert">
          <Text style={styles.body} maxFontSizeMultiplier={2}>
            {error}
          </Text>
        </View>
      ) : null}

      {plan ? (
        <Text style={styles.summary} maxFontSizeMultiplier={2}>
          {`Week of ${plan.week_start}. ${formatKm(plan.week_km)} across seven days. ${plan.rationale}`}
        </Text>
      ) : null}

      {plan?.sessions.map((session) => (
        <SessionRow key={session.id} session={session} onRequestChange={onRequestChange} />
      ))}

      {pending ? (
        <View style={styles.noticeCard} accessible accessibilityLiveRegion="polite" accessibilityRole="alert">
          <Text style={styles.notice} maxFontSizeMultiplier={2}>
            {pending}
          </Text>
        </View>
      ) : null}

      {error ? <ActionButton label="Try again" variant="secondary" onPress={reload} /> : null}
    </ScrollView>
  );
}

function SessionRow({
  session,
  onRequestChange,
}: {
  session: Session;
  onRequestChange: (session: Session) => void;
}) {
  const attention = guideNeedsAttention(session);
  const change = useCallback(() => onRequestChange(session), [onRequestChange, session]);

  return (
    <View style={styles.row}>
      {/* The row itself: one element, one sentence, one focus stop. */}
      <Pressable
        accessible
        accessibilityRole="text"
        accessibilityLabel={sessionSentence(session)}
        accessibilityHint="Long press to draft a change request, or use the Change session button below."
        onLongPress={change}
        delayLongPress={500}
        style={styles.rowBody}
      >
        <View style={styles.rowHeader}>
          <Text style={styles.day} maxFontSizeMultiplier={2}>
            {weekdayShort(session.date)}
          </Text>
          <Text style={styles.kind} maxFontSizeMultiplier={2}>
            {sessionLabel(session)}
          </Text>
        </View>
        <Text style={styles.body} maxFontSizeMultiplier={2}>
          {session.kind === 'rest' ? 'No running planned' : `${formatKm(session.km)} · ${session.venue}`}
        </Text>
        {/* Guide state: the word is the signal. `attention` only changes the
            text colour and adds a written marker, never replaces the words. */}
        <Text style={[styles.status, attention && styles.statusAttention]} maxFontSizeMultiplier={2}>
          {attention ? `Needs attention — ${humanStatus(session.guide_status)}` : humanStatus(session.guide_status)}
        </Text>
      </Pressable>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Change session: ${sessionLabel(session)} on ${session.date}`}
        accessibilityHint="Records a change request for review; it does not re-plan automatically."
        onPress={change}
        style={({ pressed }) => [styles.changeButton, pressed && styles.changeButtonPressed]}
      >
        <Text style={styles.changeLabel} maxFontSizeMultiplier={2}>
          Change session
        </Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl },
  heading: { color: colors.text, fontSize: fontSize.title, fontWeight: '800' },
  summary: { color: colors.textMuted, fontSize: fontSize.body },
  body: { color: colors.text, fontSize: fontSize.body },
  row: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: 'hidden',
  },
  rowBody: { padding: spacing.lg, gap: spacing.xs, minHeight: TOUCH_TARGET, justifyContent: 'center' },
  rowHeader: { flexDirection: 'row', alignItems: 'baseline', gap: spacing.sm, flexWrap: 'wrap' },
  day: { color: colors.textMuted, fontSize: fontSize.body, fontWeight: '700', letterSpacing: 1 },
  kind: { color: colors.text, fontSize: fontSize.lead, fontWeight: '700' },
  status: { color: colors.textMuted, fontSize: fontSize.body },
  statusAttention: { color: colors.attention, fontWeight: '700' },
  changeButton: {
    minHeight: TOUCH_TARGET,
    minWidth: TOUCH_TARGET,
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.secondary,
  },
  changeButtonPressed: { backgroundColor: colors.surfaceMuted },
  changeLabel: { color: colors.text, fontSize: fontSize.body, fontWeight: '700' },
  errorCard: {
    backgroundColor: colors.surfaceMuted,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.danger,
    padding: spacing.lg,
  },
  noticeCard: {
    backgroundColor: colors.surfaceMuted,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.attention,
    padding: spacing.lg,
  },
  notice: { color: colors.attention, fontSize: fontSize.body },
});
