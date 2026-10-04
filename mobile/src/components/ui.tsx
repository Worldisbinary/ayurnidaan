import { Ionicons } from '@expo/vector-icons';
import type { ComponentProps, PropsWithChildren, ReactNode } from 'react';
import {
  ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View,
  useWindowDimensions, type StyleProp, type TextStyle, type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { font, radius, space, usePalette } from '@/lib/theme';

type IconName = ComponentProps<typeof Ionicons>['name'];

export function Screen({ children, onRefresh, refreshing = false }: PropsWithChildren<{
  onRefresh?: () => void; refreshing?: boolean;
}>) {
  const c = usePalette();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.screen}
        refreshControl={onRefresh ? <RefreshControl refreshing={refreshing} onRefresh={onRefresh} /> : undefined}>
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function T({ children, v = 'body', style, numberOfLines }: {
  children: ReactNode; v?: 'h1' | 'h2' | 'h3' | 'body' | 'muted' | 'small' | 'label' | 'mono';
  style?: StyleProp<TextStyle>; numberOfLines?: number;
}) {
  const c = usePalette();
  const map: Record<string, TextStyle> = {
    h1: { fontSize: font.xxl, fontWeight: '700', color: c.text },
    h2: { fontSize: font.xl, fontWeight: '700', color: c.text },
    h3: { fontSize: font.lg, fontWeight: '600', color: c.text },
    body: { fontSize: font.md, color: c.text, lineHeight: 18 },
    muted: { fontSize: font.md, color: c.textMuted, lineHeight: 18 },
    small: { fontSize: font.sm, color: c.textMuted },
    label: { fontSize: font.xs, color: c.textFaint, fontWeight: '600', letterSpacing: 0.4, textTransform: 'uppercase' },
    mono: { fontSize: font.sm, color: c.textMuted, fontFamily: 'monospace' },
  };
  return <Text style={[map[v], style]} numberOfLines={numberOfLines}>{children}</Text>;
}

export function Card({ title, right, children, style }: PropsWithChildren<{
  title?: string; right?: ReactNode; style?: StyleProp<ViewStyle>;
}>) {
  const c = usePalette();
  return (
    <View style={[styles.card, { backgroundColor: c.surface, borderColor: c.border }, style]}>
      {(title || right) && (
        <View style={styles.cardHead}>
          {title ? <T v="label">{title}</T> : <View />}
          {right}
        </View>
      )}
      {children}
    </View>
  );
}

/** Lays children out in 1-3 columns depending on screen width (phone / tablet / desktop web). */
export function Columns({ children, min = 340 }: PropsWithChildren<{ min?: number }>) {
  const { width } = useWindowDimensions();
  const n = Math.max(1, Math.min(3, Math.floor((Math.min(width, 1400) - 2 * space.lg) / min)));
  const items = (Array.isArray(children) ? children : [children]).filter(Boolean);
  const cols: ReactNode[][] = Array.from({ length: n }, () => []);
  items.forEach((child, i) => cols[i % n].push(child));
  return (
    <View style={{ flexDirection: 'row', gap: space.md }}>
      {cols.map((col, i) => (
        <View key={i} style={{ flex: 1, gap: space.md, minWidth: 0 }}>{col}</View>
      ))}
    </View>
  );
}

export function Row({ children, style }: PropsWithChildren<{ style?: StyleProp<ViewStyle> }>) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap: space.sm, flexWrap: 'wrap' }, style]}>{children}</View>;
}

export function Button({ label, onPress, variant = 'primary', loading, disabled, icon, compact }: {
  label: string; onPress: () => void; variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  loading?: boolean; disabled?: boolean; icon?: IconName; compact?: boolean;
}) {
  const c = usePalette();
  const bg = { primary: c.accent, secondary: c.surfaceAlt, danger: c.critical, ghost: 'transparent' }[variant];
  const fg = variant === 'primary' || variant === 'danger' ? '#fff' : c.text;
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.button,
        compact && { paddingVertical: 5, paddingHorizontal: 10 },
        { backgroundColor: bg, opacity: disabled ? 0.45 : pressed ? 0.8 : 1, borderColor: c.border },
        variant === 'ghost' && { borderWidth: 1 },
      ]}>
      {loading ? <ActivityIndicator color={fg} size="small" /> : icon ? <Ionicons name={icon} size={15} color={fg} /> : null}
      <Text style={{ color: fg, fontWeight: '600', fontSize: font.md }}>{label}</Text>
    </Pressable>
  );
}

export function Chip({ label, selected, onPress, tone }: {
  label: string; selected?: boolean; onPress?: () => void; tone?: 'yes' | 'no';
}) {
  const c = usePalette();
  const bg = tone === 'yes' ? c.accentSoft : tone === 'no' ? c.surfaceAlt : selected ? c.accentSoft : c.surface;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityState={{ selected: !!selected }}
      style={[styles.chip, { backgroundColor: bg, borderColor: selected || tone === 'yes' ? c.accent : c.border }]}>
      {tone === 'yes' && <Ionicons name="checkmark" size={12} color={c.text} />}
      {tone === 'no' && <Ionicons name="close" size={12} color={c.textMuted} />}
      <Text style={{ fontSize: font.sm, color: tone === 'no' ? c.textMuted : c.text,
        textDecorationLine: tone === 'no' ? 'line-through' : 'none' }}>{label}</Text>
    </Pressable>
  );
}

export function Field({ label, ...props }: { label: string } & ComponentProps<typeof TextInput>) {
  const c = usePalette();
  return (
    <View style={{ gap: 3, flexGrow: 1 }}>
      <T v="label">{label}</T>
      <TextInput
        placeholderTextColor={c.textFaint}
        {...props}
        style={[styles.input, { borderColor: c.border, color: c.text, backgroundColor: c.surface }, props.style]}
      />
    </View>
  );
}

const STATUS: Record<string, { icon: IconName; label: string; tone: 'critical' | 'serious' | 'good' | 'muted' | 'accent' }> = {
  emergency: { icon: 'alert-circle', label: 'Emergency', tone: 'critical' },
  urgent: { icon: 'warning', label: 'Urgent', tone: 'serious' },
  routine: { icon: 'checkmark-circle', label: 'Routine', tone: 'good' },
  draft: { icon: 'create-outline', label: 'Draft', tone: 'muted' },
  submitted: { icon: 'paper-plane-outline', label: 'With practitioner', tone: 'accent' },
  reviewed: { icon: 'medkit-outline', label: 'Reviewed', tone: 'good' },
  confirmed: { icon: 'checkmark-done', label: 'Confirmed', tone: 'good' },
};

export function Badge({ status }: { status: string }) {
  const c = usePalette();
  const s = STATUS[status] ?? { icon: 'ellipse-outline' as IconName, label: status, tone: 'muted' as const };
  const color = { critical: c.critical, serious: c.serious, good: c.good, muted: c.textMuted, accent: c.accent }[s.tone];
  return (
    <View style={[styles.badge, { borderColor: color }]}>
      <Ionicons name={s.icon} size={12} color={color} />
      <Text style={{ fontSize: font.xs, fontWeight: '700', color }}>{s.label}</Text>
    </View>
  );
}

/** Horizontal bar with a text value, for shares / likelihoods (never colour-only). */
export function Bar({ label, value, color, suffix = '%', max = 1 }: {
  label: string; value: number; color: string; suffix?: string; max?: number;
}) {
  const c = usePalette();
  const pct = Math.max(0, Math.min(1, value / max));
  return (
    <View style={{ gap: 2 }} accessibilityLabel={`${label} ${Math.round(value * 100)}${suffix}`}>
      <Row style={{ justifyContent: 'space-between' }}>
        <T v="small">{label}</T>
        <T v="small" style={{ color: c.text, fontVariant: ['tabular-nums'] }}>{(value * 100).toFixed(0)}{suffix}</T>
      </Row>
      <View style={[styles.track, { backgroundColor: c.surfaceAlt }]}>
        <View style={{ width: `${pct * 100}%`, height: '100%', backgroundColor: color, borderRadius: 3 }} />
      </View>
    </View>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <View style={{ gap: 4 }}>
      {items.map(([k, v]) => (
        <Row key={k} style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
          <T v="small">{k}</T>
          {typeof v === 'string' || typeof v === 'number' ? <T style={{ textAlign: 'right', flexShrink: 1 }}>{v}</T> : v}
        </Row>
      ))}
    </View>
  );
}

export function Table({ head, rows, flex, onRowPress }: {
  head: string[]; rows: ReactNode[][]; flex?: number[]; onRowPress?: (i: number) => void;
}) {
  const c = usePalette();
  const f = flex ?? head.map(() => 1);
  return (
    <View>
      <View style={[styles.tr, { borderColor: c.border }]}>
        {head.map((h, i) => (
          <View key={h} style={{ flex: f[i] }}><T v="label">{h}</T></View>
        ))}
      </View>
      {rows.map((r, ri) => (
        <Pressable key={ri} onPress={onRowPress ? () => onRowPress(ri) : undefined}
          style={({ pressed }) => [styles.tr, { borderColor: c.border, backgroundColor: pressed ? c.surfaceAlt : 'transparent' }]}>
          {r.map((cell, ci) => (
            <View key={ci} style={{ flex: f[ci], paddingRight: 6 }}>
              {typeof cell === 'string' || typeof cell === 'number' ? <T numberOfLines={2}>{cell}</T> : cell}
            </View>
          ))}
        </Pressable>
      ))}
    </View>
  );
}

export function Notice({ tone = 'info', icon, children }: PropsWithChildren<{ tone?: 'info' | 'warning' | 'critical'; icon?: IconName }>) {
  const c = usePalette();
  const bg = { info: c.surfaceAlt, warning: c.warningSoft, critical: c.criticalSoft }[tone];
  const fg = { info: c.textMuted, warning: c.warning, critical: c.critical }[tone];
  const ic: IconName = icon ?? ({ info: 'information-circle', warning: 'warning', critical: 'alert-circle' } as const)[tone];
  return (
    <View style={[styles.notice, { backgroundColor: bg, borderColor: fg }]}>
      <Ionicons name={ic} size={16} color={fg} style={{ marginTop: 1 }} />
      <View style={{ flex: 1, gap: 2 }}>{children}</View>
    </View>
  );
}

export function Loading() {
  const c = usePalette();
  return <View style={{ padding: space.xl }}><ActivityIndicator color={c.accent} /></View>;
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <Notice tone="critical"><T>{error instanceof Error ? error.message : String(error)}</T></Notice>;
}

const styles = StyleSheet.create({
  screen: { padding: space.lg, gap: space.md, width: '100%', maxWidth: 1400, alignSelf: 'center' },
  card: { borderWidth: 1, borderRadius: radius, padding: space.md, gap: space.sm },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  button: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 9,
    paddingHorizontal: 14, borderRadius: radius },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: 999,
    paddingHorizontal: 9, paddingVertical: 4 },
  input: { borderWidth: 1, borderRadius: radius, paddingHorizontal: 10, paddingVertical: 8, fontSize: font.md },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 3, borderWidth: 1, borderRadius: 999,
    paddingHorizontal: 7, paddingVertical: 2, alignSelf: 'flex-start' },
  track: { height: 6, borderRadius: 3, overflow: 'hidden' },
  tr: { flexDirection: 'row', paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth, alignItems: 'center' },
  notice: { flexDirection: 'row', gap: 8, borderLeftWidth: 3, borderRadius: radius, padding: space.md },
});
