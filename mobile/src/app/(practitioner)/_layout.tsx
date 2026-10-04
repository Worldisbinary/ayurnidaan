import { Tabs } from 'expo-router';

import { tabIcon as icon } from '@/components/tab-icon';
import { usePalette } from '@/lib/theme';

export default function PractitionerTabs() {
  const c = usePalette();
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: c.accent,
      tabBarStyle: { backgroundColor: c.surface, borderTopColor: c.border } }}>
      <Tabs.Screen name="index" options={{ title: 'Queue', tabBarIcon: icon('list-outline') }} />
      <Tabs.Screen name="insights" options={{ title: 'Insights', tabBarIcon: icon('analytics-outline') }} />
      <Tabs.Screen name="account" options={{ title: 'Account', tabBarIcon: icon('person-outline') }} />
      <Tabs.Screen name="case/[id]" options={{ href: null }} />
    </Tabs>
  );
}
