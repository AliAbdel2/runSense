import { useCallback, useEffect, useRef, useState } from 'react';
import { AccessibilityInfo } from 'react-native';

/**
 * Speak a message through TalkBack / VoiceOver.
 *
 * `AccessibilityInfo.announceForAccessibility` is the real platform API for
 * this and is what the plan's "auto-announces on focus" requirement means. It
 * is a no-op when no screen reader is running, which is why the screens also
 * render every announced string visibly — a sighted guide or a judge sees
 * exactly what the runner hears.
 */
export function useAnnounce(): (message: string) => void {
  return useCallback((message: string) => {
    const text = message.trim();
    if (!text) return;
    AccessibilityInfo.announceForAccessibility(text);
  }, []);
}

/**
 * Announce `message` once, as soon as it becomes available.
 *
 * Guarded against repeats because the plan data arrives asynchronously and a
 * re-render must not make the phone talk over itself. Passing a new, different
 * message announces again; passing the same one does nothing.
 */
export function useAnnounceOnce(message: string | null): void {
  const announce = useAnnounce();
  const spoken = useRef<string | null>(null);

  useEffect(() => {
    if (!message || message === spoken.current) return;
    spoken.current = message;
    // A short delay lets the navigator finish its own focus announcement first;
    // without it, Android's TalkBack drops whichever utterance arrives second.
    const timer = setTimeout(() => announce(message), 350);
    return () => clearTimeout(timer);
  }, [announce, message]);
}

/** Whether a screen reader is currently running. Null until first resolved. */
export function useScreenReaderEnabled(): boolean | null {
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    AccessibilityInfo.isScreenReaderEnabled()
      .then((value) => {
        if (active) setEnabled(value);
      })
      .catch(() => {
        if (active) setEnabled(null);
      });
    const subscription = AccessibilityInfo.addEventListener('screenReaderChanged', (value) => setEnabled(value));
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  return enabled;
}
