import { Redirect } from 'expo-router';

import { useSession } from '@/lib/session';

// Entry point: route each role to its own workspace.
export default function Index() {
  const { user } = useSession();
  if (!user) return <Redirect href="/sign-in" />;
  if (user.role === 'practitioner') return <Redirect href="/(practitioner)" />;
  if (user.role === 'admin') return <Redirect href="/(admin)" />;
  return <Redirect href="/(patient)" />;
}
