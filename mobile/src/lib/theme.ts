/**
 * A deliberately small design token set.
 *
 * Two rules this file exists to enforce:
 *  - `TOUCH_TARGET` is the plan's 64 px minimum. Every interactive element in
 *    this app sets both `minWidth` and `minHeight` from it.
 *  - Colour never carries meaning on its own. Wherever a colour marks a state,
 *    the same state is spelled out in text as well, so the screen is readable
 *    without colour perception and the screen reader hears the state rather
 *    than inferring it from a swatch.
 */

export const TOUCH_TARGET = 64;

export const colors = {
  background: '#0B1220',
  surface: '#16203A',
  surfaceMuted: '#101A30',
  border: '#2A3757',
  text: '#F2F5FF',
  textMuted: '#B4C0DC',
  primary: '#3D7BFF',
  primaryPressed: '#2B5FD0',
  onPrimary: '#FFFFFF',
  secondary: '#1F2B4A',
  attention: '#FFB020',
  danger: '#FF5A5A',
  ok: '#4ADE80',
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 14,
  lg: 20,
} as const;

export const fontSize = {
  body: 17,
  lead: 20,
  title: 26,
  display: 40,
  huge: 64,
} as const;
