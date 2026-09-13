import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

import { colors } from '@/lib/theme';

/**
 * Expo Router file-based stack.
 *
 * A stack, not tabs: the plan's three screens are a sequence, not peers. Home
 * is where the app opens and speaks; Live run is entered by the one primary
 * action; Week plan is a detour off Home. A stack also gives every screen a
 * real back affordance that both platforms' screen readers already understand,
 * which a custom tab bar would have to reimplement.
 *
 * Routes: src/app/index.tsx → "/", live.tsx → "/live", week.tsx → "/week".
 */
export default function RootLayout() {
  return (
    <>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.background },
          headerTintColor: colors.text,
          headerTitleStyle: { color: colors.text },
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        <Stack.Screen name="index" options={{ title: 'Today' }} />
        <Stack.Screen name="live" options={{ title: 'Live run' }} />
        <Stack.Screen name="week" options={{ title: 'Week plan' }} />
      </Stack>
    </>
  );
}
