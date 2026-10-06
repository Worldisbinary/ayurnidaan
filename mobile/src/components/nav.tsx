// Responsive app shell: bottom tabs on phones, a labelled sidebar on tablets / desktop web.
// Both are the same Expo Router <Tabs> navigator, so routes and deep links don't change.
import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';
import type { ComponentProps } from 'react';
import { Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { tabIcon } from '@/components/tab-icon';
import { useSession } from '@/lib/session';
import { font, radius, space, usePalette } from '@/lib/theme';

type IconName = ComponentProps<typeof Ionicons>['name'];
export interface NavItem { name: string; title: string; icon: IconName }

export const WIDE = 900;

export function AppTabs({ items, hidden = [], role }: { items: NavItem[]; hidden?: string[]; role: string }) {
  const c = usePalette();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const wide = width >= WIDE;
  return (
    <Tabs
      tabBar={wide ? (props) => <Sidebar {...props} items={items} role={role} /> : undefined}
      screenOptions={{
        headerShown: false,
        tabBarPosition: wide ? 'left' : 'bottom',
        tabBarActiveTintColor: c.accent,
        tabBarInactiveTintColor: c.textMuted,
        tabBarStyle: { backgroundColor: c.surface, borderTopColor: c.border, height: 64 + insets.bottom,
          paddingTop: 4, paddingBottom: Math.max(insets.bottom, 8) },
        tabBarLabelStyle: { fontSize: font.xs, fontWeight: '600' },
      }}>
      {items.map((i) => (
        <Tabs.Screen key={i.name} name={i.name} options={{ title: i.title, tabBarIcon: tabIcon(i.icon as keyof typeof Ionicons.glyphMap) }} />
      ))}
      {hidden.map((name) => <Tabs.Screen key={name} name={name} options={{ href: null }} />)}
    </Tabs>
  );
}

interface SidebarProps {
  state: { index: number; routes: { key: string; name: string }[] };
  navigation: { navigate: (name: string) => void; emit: (e: { type: 'tabPress'; target: string; canPreventDefault: true }) => { defaultPrevented: boolean } };
  items: NavItem[];
  role: string;
}

function Sidebar({ state, navigation, items, role }: SidebarProps) {
  const c = usePalette();
  const insets = useSafeAreaInsets();
  const { user, signOut } = useSession();
  const current = state.routes[state.index]?.name;
  return (
    <View
      accessibilityRole="tablist"
      style={[styles.sidebar, { backgroundColor: c.surface, borderRightColor: c.border, paddingTop: insets.top + space.lg }]}>
      <View style={styles.brand}>
        <View style={[styles.logo, { backgroundColor: c.accent }]}>
          <Ionicons name="leaf" size={16} color={c.onAccent} />
        </View>
        <View>
          <Text style={{ color: c.text, fontWeight: '800', fontSize: font.lg }}>Ayurnidaan</Text>
          <Text style={{ color: c.textFaint, fontSize: font.xs, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.4 }}>{role}</Text>
        </View>
      </View>

      <View style={{ gap: 2 }}>
        {items.map((item) => {
          const route = state.routes.find((r) => r.name === item.name);
          const active = current === item.name;
          return (
            <Pressable
              key={item.name}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
              accessibilityLabel={item.title}
              onPress={() => {
                if (!route) return;
                const e = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
                if (!active && !e.defaultPrevented) navigation.navigate(item.name);
              }}
              style={({ pressed, hovered }: { pressed: boolean; hovered?: boolean }) => [
                styles.item,
                { backgroundColor: active ? c.accentSoft : pressed || hovered ? c.surfaceAlt : 'transparent' },
              ]}>
              <View style={[styles.activeBar, { backgroundColor: active ? c.accent : 'transparent' }]} />
              <Ionicons name={item.icon} size={18} color={active ? c.accent : c.textMuted} />
              <Text style={{ color: active ? c.text : c.textMuted, fontWeight: active ? '700' : '500', fontSize: font.md }}>{item.title}</Text>
            </Pressable>
          );
        })}
      </View>

      <View style={{ flex: 1 }} />

      <View style={[styles.sos, { borderColor: c.critical, backgroundColor: c.criticalSoft }]}>
        <Ionicons name="call" size={14} color={c.critical} />
        <Text style={{ color: c.critical, fontSize: font.sm, fontWeight: '700', flexShrink: 1 }}>Emergency? Call 112 / 108</Text>
      </View>
      <View style={[styles.user, { borderTopColor: c.border }]}>
        <View style={[styles.avatar, { backgroundColor: c.surfaceAlt }]}>
          <Text style={{ color: c.text, fontWeight: '700' }}>{(user?.full_name ?? '?').slice(0, 1).toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={{ color: c.text, fontWeight: '600', fontSize: font.md }} numberOfLines={1}>{user?.full_name}</Text>
          <Text style={{ color: c.textFaint, fontSize: font.xs }} numberOfLines={1}>{user?.email}</Text>
        </View>
        <Pressable onPress={() => signOut()} accessibilityRole="button" accessibilityLabel="Sign out" hitSlop={8}>
          <Ionicons name="log-out-outline" size={18} color={c.textMuted} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  sidebar: { width: 232, borderRightWidth: StyleSheet.hairlineWidth, paddingHorizontal: space.md, paddingBottom: space.md, gap: space.lg },
  brand: { flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingHorizontal: space.sm },
  logo: { width: 30, height: 30, borderRadius: 8, alignItems: 'center', justifyContent: 'center' },
  item: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: 9, paddingRight: space.md, borderRadius: radius, overflow: 'hidden' },
  activeBar: { width: 3, alignSelf: 'stretch', borderRadius: 2, marginRight: 2 },
  sos: { flexDirection: 'row', alignItems: 'center', gap: space.sm, borderWidth: 1, borderRadius: radius, padding: space.sm },
  user: { flexDirection: 'row', alignItems: 'center', gap: space.sm, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: space.md },
  avatar: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
});
