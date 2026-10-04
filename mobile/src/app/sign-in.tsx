import { Link, router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Button, Card, ErrorText, Field, Notice, Screen, T } from '@/components/ui';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';

export default function SignIn() {
  const { signIn } = useSession();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
      router.replace('/');
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <View style={{ maxWidth: 440, width: '100%', alignSelf: 'center', gap: space.md, marginTop: space.xl }}>
        <T v="h1">Ayurnidaan</T>
        <T v="muted">Ayurvedic screening and clinical decision support.</T>
        <Card>
          <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none"
            keyboardType="email-address" autoComplete="email" textContentType="emailAddress" />
          <Field label="Password" value={password} onChangeText={setPassword} secureTextEntry
            autoComplete="password" textContentType="password" onSubmitEditing={submit} />
          <ErrorText error={error} />
          <Button label="Sign in" onPress={submit} loading={busy} disabled={!email || !password} />
        </Card>
        <T v="muted">New here? <Link href="/register"><T style={{ fontWeight: '700' }}>Create an account</T></Link></T>
        <Notice>
          <T v="small">Not for emergencies. If you have chest pain, trouble breathing or signs of stroke, call 112 / 108.</T>
        </Notice>
        <Link href="/privacy"><T v="small">Privacy policy</T></Link>
      </View>
    </Screen>
  );
}
