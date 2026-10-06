import { AppTabs } from '@/components/nav';

export default function PatientTabs() {
  return (
    <AppTabs
      role="Patient"
      items={[
        { name: 'index', title: 'Home', icon: 'home-outline' },
        { name: 'today', title: 'Today', icon: 'sunny-outline' },
        { name: 'check', title: 'New check', icon: 'add-circle-outline' },
        { name: 'history', title: 'History', icon: 'time-outline' },
        { name: 'profile', title: 'Profile', icon: 'person-outline' },
      ]}
      hidden={['encounter/[id]', 'prakriti', 'module/[id]']}
    />
  );
}
