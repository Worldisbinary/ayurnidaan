import { Tabs } from 'expo-router';

import { tabIcon as icon } from '@/components/tab-icon';
import { usePalette } from '@/lib/theme';

export default function PatientTabs() {
  const c = usePalette();
  return (
    <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: c.accent,
      tabBarStyle: { backgroundColor: c.surface, borderTopColor: c.border } }}>
      <Tabs.Screen name="index" options={{ title: 'Home', tabBarIcon: icon('home-outline') }} />
      <Tabs.Screen name="check" options={{ title: 'New check', tabBarIcon: icon('add-circle-outline') }} />
      <Tabs.Screen name="history" options={{ title: 'History', tabBarIcon: icon('time-outline') }} />
      <Tabs.Screen name="profile" options={{ title: 'Profile', tabBarIcon: icon('person-outline') }} />
      <Tabs.Screen name="encounter/[id]" options={{ href: null }} />
      <Tabs.Screen name="prakriti" options={{ href: null }} />
    </Tabs>
  );
}
