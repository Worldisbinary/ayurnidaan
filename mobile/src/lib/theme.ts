// Dense, data-rich clinical theme. Colours are tokens with light + dark values; dosha
// identity uses the validated categorical slots 1-3 (blue / orange / aqua) and status
// colours always ship with an icon + label, never colour alone.
import { useColorScheme } from 'react-native';

const light = {
  bg: '#f6f5f2',
  surface: '#fcfcfb',
  surfaceAlt: '#efede8',
  border: '#dedcd5',
  text: '#0b0b0b',
  textMuted: '#52514e',
  textFaint: '#8a8984',
  accent: '#1c5cab',
  accentSoft: '#cde2fb',
  vata: '#2a78d6',
  pitta: '#eb6834',
  kapha: '#1baf7a',
  good: '#0ca30c',
  warning: '#b77800',
  serious: '#c4581f',
  critical: '#d03b3b',
  criticalSoft: '#fbe3e3',
  warningSoft: '#fdf1d6',
};

const dark: typeof light = {
  bg: '#121211',
  surface: '#1a1a19',
  surfaceAlt: '#242422',
  border: '#33332f',
  text: '#ffffff',
  textMuted: '#c3c2b7',
  textFaint: '#8a8984',
  accent: '#6da7ec',
  accentSoft: '#184f95',
  vata: '#3987e5',
  pitta: '#d95926',
  kapha: '#199e70',
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#e66767',
  criticalSoft: '#3a1d1d',
  warningSoft: '#3a2f14',
};

export type Palette = typeof light;

export function usePalette(): Palette {
  return useColorScheme() === 'dark' ? dark : light;
}

export const space = { xs: 4, sm: 6, md: 10, lg: 14, xl: 20 };
export const font = { xs: 11, sm: 12, md: 13, lg: 15, xl: 18, xxl: 22 };
export const radius = 6;

export const DOSHA_ORDER = ['vata', 'pitta', 'kapha'] as const;

export const RITU_LABEL: Record<string, string> = {
  shishira: 'Shishira · late winter',
  vasanta: 'Vasanta · spring',
  grishma: 'Grishma · summer',
  varsha: 'Varsha · monsoon',
  sharad: 'Sharad · autumn',
  hemanta: 'Hemanta · early winter',
};

export const DESHA_LABEL: Record<string, string> = {
  jangala: 'Jangala · arid',
  anupa: 'Anupa · humid / marshy',
  sadharana: 'Sadharana · temperate',
};

export const pretty = (s: string | null | undefined) =>
  (s ?? '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
