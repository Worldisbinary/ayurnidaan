import { Badge, Button, Card, KV, Screen, T } from '@/components/ui';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';

export default function Account() {
  const { user, signOut } = useSession();
  return (
    <Screen>
      <T v="h1">Account</T>
      <Card title="Practitioner">
        <KV items={[['Name', user?.full_name ?? ''], ['Email', user?.email ?? '']]} />
        <Badge status={user?.practitioner_verified ? 'confirmed' : 'draft'} />
      </Card>
      <Button label="Sign out on all devices" variant="secondary" onPress={async () => { await api.logoutAll(); await signOut(); }} />
      <Button label="Sign out" variant="ghost" onPress={signOut} />
    </Screen>
  );
}
