import { AppTabs } from '@/components/nav';

export default function PractitionerTabs() {
  return (
    <AppTabs
      role="Practitioner"
      items={[
        { name: 'index', title: 'Queue', icon: 'list-outline' },
        { name: 'insights', title: 'Insights', icon: 'analytics-outline' },
        { name: 'account', title: 'Account', icon: 'person-outline' },
      ]}
      hidden={['case/[id]']}
    />
  );
}
