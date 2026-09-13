import * as Haptics from 'expo-haptics';
import type { ReactNode } from 'react';
import { useCallback } from 'react';
import { Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { TOUCH_TARGET, colors, fontSize, radius, spacing } from '@/lib/theme';

export type ActionButtonVariant = 'primary' | 'secondary';

export interface ActionButtonProps {
  /** Visible text. Also the spoken label unless `accessibilityLabel` overrides it. */
  label: string;
  /** Smaller text under the label. Read after the label by the screen reader. */
  caption?: string;
  onPress: () => void;
  onLongPress?: () => void;
  onPressIn?: () => void;
  onPressOut?: () => void;
  variant?: ActionButtonVariant;
  disabled?: boolean;
  busy?: boolean;
  /** Override only when the visible text is not the whole story. */
  accessibilityLabel?: string;
  /**
   * What happens next. Supplied only where it adds information the label does
   * not already carry — an unhelpful hint is noise on every single focus.
   */
  accessibilityHint?: string;
  style?: StyleProp<ViewStyle>;
  children?: ReactNode;
}

/**
 * The one button type this app uses.
 *
 * Guarantees, so no screen has to remember them:
 *  - at least 64 x 64 points of touch target (`TOUCH_TARGET`);
 *  - `accessibilityRole="button"` and an explicit `accessibilityLabel`;
 *  - `accessibilityState` carries disabled/busy, rather than colour alone;
 *  - a haptic tap on every successful primary press.
 */
export function ActionButton({
  label,
  caption,
  onPress,
  onLongPress,
  onPressIn,
  onPressOut,
  variant = 'primary',
  disabled = false,
  busy = false,
  accessibilityLabel,
  accessibilityHint,
  style,
  children,
}: ActionButtonProps) {
  const blocked = disabled || busy;

  const handlePress = useCallback(() => {
    if (blocked) return;
    // Confirmation you can feel: the plan asks for haptic confirmation on the
    // primary action, and a runner mid-stride should not have to look. Haptics
    // are unavailable on web and on some Android hardware, so failure here is
    // ignored rather than surfaced.
    void Haptics.impactAsync(
      variant === 'primary' ? Haptics.ImpactFeedbackStyle.Heavy : Haptics.ImpactFeedbackStyle.Light,
    ).catch(() => undefined);
    onPress();
  }, [blocked, onPress, variant]);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? (caption ? `${label}. ${caption}` : label)}
      {...(accessibilityHint ? { accessibilityHint } : {})}
      accessibilityState={{ disabled: blocked, busy }}
      disabled={blocked}
      onPress={handlePress}
      {...(onLongPress ? { onLongPress } : {})}
      {...(onPressIn ? { onPressIn } : {})}
      {...(onPressOut ? { onPressOut } : {})}
      style={({ pressed }) => [
        styles.base,
        variant === 'primary' ? styles.primary : styles.secondary,
        pressed && (variant === 'primary' ? styles.primaryPressed : styles.secondaryPressed),
        blocked && styles.blocked,
        style,
      ]}
    >
      <View style={styles.content} pointerEvents="none">
        <Text
          style={[styles.label, variant === 'primary' ? styles.labelPrimary : styles.labelSecondary]}
          maxFontSizeMultiplier={2.5}
        >
          {label}
        </Text>
        {caption ? (
          <Text style={styles.caption} maxFontSizeMultiplier={2.5}>
            {caption}
          </Text>
        ) : null}
        {busy ? (
          // Spelled out, not spun: "busy" must survive both no-colour and
          // no-animation perception.
          <Text style={styles.caption} maxFontSizeMultiplier={2.5}>
            Working…
          </Text>
        ) : null}
        {children}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: TOUCH_TARGET,
    minWidth: TOUCH_TARGET,
    borderRadius: radius.lg,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.lg,
    justifyContent: 'center',
    borderWidth: 2,
  },
  primary: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
    minHeight: 96,
  },
  primaryPressed: { backgroundColor: colors.primaryPressed, borderColor: colors.primaryPressed },
  secondary: { backgroundColor: colors.secondary, borderColor: colors.border },
  secondaryPressed: { backgroundColor: colors.surfaceMuted },
  blocked: { opacity: 0.55 },
  content: { gap: spacing.xs },
  label: { fontSize: fontSize.lead, fontWeight: '700' },
  labelPrimary: { color: colors.onPrimary },
  labelSecondary: { color: colors.text },
  caption: { fontSize: fontSize.body, color: colors.textMuted },
});
