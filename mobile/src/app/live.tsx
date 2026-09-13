import { useRouter } from 'expo-router';
import { useCallback, useEffect } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Camera, useCameraDevice, useCameraPermission } from 'react-native-vision-camera';
import { useAudioPlayer } from 'expo-audio';
import * as Speech from 'expo-speech';

import { ActionButton } from '@/components/ActionButton';
import { useAnnounce, useAnnounceOnce } from '@/hooks/useAnnounce';
import { usePerceptionStream } from '@/hooks/usePerceptionStream';
import { colors, fontSize, radius, spacing } from '@/lib/theme';

/**
 * Live run — a debug view, not the interface.
 *
 * The runner's interface during a run is audio and haptics; this screen exists
 * so a sighted guide or a judge can see what the runner is being told. It shows
 * the current zone and the last alert in large type.
 *
 * The camera/model path is wired here, but its native runtime still requires an
 * Expo development build and has not been run in this environment.
 */
export default function LiveRunScreen() {
  const router = useRouter();
  const announce = useAnnounce();
  const perception = usePerceptionStream();
  const device = useCameraDevice('back');
  const permission = useCameraPermission();
  useEffect(() => { if (!permission.hasPermission) void permission.requestPermission(); }, [permission]);
  const dangerTone = useAudioPlayer(require('../../assets/audio/double_tone.wav'));
  const leftTone = useAudioPlayer(require('../../assets/audio/panned_tone_left.wav'));
  const rightTone = useAudioPlayer(require('../../assets/audio/panned_tone_right.wav'));
  const softTone = useAudioPlayer(require('../../assets/audio/soft_cue.wav'));

  useEffect(() => {
    const event = perception.lastAlert;
    if (!event) return;
    const player = event.earcon === 'double_tone' ? dangerTone : event.earcon === 'panned_tone_left' ? leftTone : event.earcon === 'panned_tone_right' ? rightTone : softTone;
    player.seekTo(0); player.play();
    Speech.speak(event.utterance, { language: 'en-US', rate: 1.05 });
  }, [dangerTone, leftTone, rightTone, softTone, perception.lastAlert]);

  useAnnounceOnce(`Live run screen. ${perception.statusText}`);

  const onEnd = useCallback(() => {
    announce('Session ended.');
    router.back();
  }, [announce, router]);

  const zoneText = perception.lastAlert ? perception.lastAlert.zone.toUpperCase() : 'NO SIGNAL';
  const alertText = perception.lastAlert?.utterance ?? 'No alerts. Detection is not running.';

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {permission.hasPermission && device && perception.frameProcessor ? (
        <Camera device={device} isActive frameProcessor={perception.frameProcessor} style={styles.camera} />
      ) : null}
      <View
        style={styles.banner}
        accessible
        accessibilityRole="alert"
        accessibilityLabel={perception.statusText}
      >
        <Text style={styles.bannerTitle} maxFontSizeMultiplier={2}>
          {permission.hasPermission && device ? 'On-device perception' : 'Perception preview needs a phone camera'}
        </Text>
        <Text style={styles.bannerBody} maxFontSizeMultiplier={2}>
          {permission.hasPermission && device ? perception.statusText : 'Camera permission or a rear camera is unavailable. Do not run by this screen.'}
        </Text>
      </View>

      {/* Zone indicator. Its state is the word inside it — the border colour
          never carries meaning on its own. */}
      <View
        style={[styles.zoneBox, perception.connected ? styles.zoneLive : styles.zoneDead]}
        accessible
        accessibilityLabel={
          perception.connected ? `Obstacle zone ${zoneText}` : 'Zone indicator inactive. No detection is running.'
        }
      >
        <Text style={styles.zoneLabel} maxFontSizeMultiplier={1.6}>
          ZONE
        </Text>
        <Text style={styles.zoneValue} maxFontSizeMultiplier={1.6} numberOfLines={1} adjustsFontSizeToFit>
          {zoneText}
        </Text>
      </View>

      <View style={styles.alertBox} accessible accessibilityLabel={`Last alert: ${alertText}`}>
        <Text style={styles.alertLabel} maxFontSizeMultiplier={2}>
          Last alert
        </Text>
        <Text style={styles.alertValue} maxFontSizeMultiplier={2}>
          {alertText}
        </Text>
        {perception.lastAlert ? (
          <Text style={styles.meta} maxFontSizeMultiplier={2}>
            {`Tier ${perception.lastAlert.tier}, ${perception.lastAlert.distance}, frame ${perception.lastAlert.frame_index}.`}
          </Text>
        ) : null}
      </View>

      <View style={styles.statusRow} accessible accessibilityLabel={`Stream status: ${perception.statusText}`}>
        <Text style={styles.meta} maxFontSizeMultiplier={2}>
          {`Stream: ${perception.connected ? 'connected' : 'disconnected'} · frames processed ${perception.framesProcessed}`}
        </Text>
        <Text style={styles.meta} maxFontSizeMultiplier={2}>
          {perception.statusText}
        </Text>
      </View>

      <ActionButton
        label="End session"
        onPress={onEnd}
        accessibilityHint="Returns to today's session."
      />

      <Text style={styles.footnote} maxFontSizeMultiplier={2}>
        Wiring note: replace the body of `usePerceptionStream` with a
        react-native-vision-camera frame processor and a TFLite YOLO11n model
        (see scripts/export_yolo_tflite.py). That needs a development build; it
        cannot run inside Expo Go.
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  camera: { width: '100%', height: 240, borderRadius: radius.md, overflow: 'hidden' },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xl },
  banner: {
    backgroundColor: colors.surfaceMuted,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.attention,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  bannerTitle: { color: colors.attention, fontSize: fontSize.lead, fontWeight: '800' },
  bannerBody: { color: colors.text, fontSize: fontSize.body },
  zoneBox: {
    borderRadius: radius.lg,
    borderWidth: 3,
    padding: spacing.lg,
    minHeight: 180,
    justifyContent: 'center',
    gap: spacing.sm,
  },
  zoneLive: { borderColor: colors.ok, backgroundColor: colors.surface },
  zoneDead: { borderColor: colors.border, backgroundColor: colors.surfaceMuted },
  zoneLabel: { color: colors.textMuted, fontSize: fontSize.body, letterSpacing: 2 },
  zoneValue: { color: colors.text, fontSize: fontSize.huge, fontWeight: '900' },
  alertBox: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  alertLabel: { color: colors.textMuted, fontSize: fontSize.body, letterSpacing: 1 },
  alertValue: { color: colors.text, fontSize: fontSize.title, fontWeight: '700' },
  statusRow: { gap: spacing.xs },
  meta: { color: colors.textMuted, fontSize: fontSize.body },
  footnote: { color: colors.textMuted, fontSize: 14, marginTop: spacing.sm },
});
