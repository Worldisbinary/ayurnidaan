import { Link, router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { Button, Card, Chip, ErrorText, Field, Row, Screen, T } from '@/components/ui';
import { useSession } from '@/lib/session';
import { space } from '@/lib/theme';

export default function Register() {
  const { signUp } = useSession();
  const [role, setRole] = useState<'patient' | 'practitioner'>('patient');
  const [form, setForm] = useState({ full_name: '', email: '', password: '', registration_number: '' });
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await signUp({
        ...form, email: form.email.trim(), role,
        registration_number: role === 'practitioner' ? form.registration_number : undefined,
      });
      router.replace('/');
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <View style={{ maxWidth: 480, width: '100%', alignSelf: 'center', gap: space.md, marginTop: space.lg }}>
        <T v="h1">Create account</T>
        <Row>
          <Chip label="I am a patient" selected={role === 'patient'} onPress={() => setRole('patient')} />
          <Chip label="I am a practitioner" selected={role === 'practitioner'} onPress={() => setRole('practitioner')} />
        </Row>
        <Card>
          <Field label="Full name" value={form.full_name} onChangeText={set('full_name')} autoComplete="name" />
          <Field label="Email" value={form.email} onChangeText={set('email')} autoCapitalize="none"
            keyboardType="email-address" autoComplete="email" />
          <Field label="Password (10+ characters)" value={form.password} onChangeText={set('password')}
            secureTextEntry autoComplete="new-password" />
          {role === 'practitioner' && (
            <>
              <Field label="State / NCISM registration number" value={form.registration_number}
                onChangeText={set('registration_number')} autoCapitalize="characters" />
              <T v="small">An administrator verifies your registration before you can see patient cases.</T>
            </>
          )}
          <Chip label="I have read the privacy policy" selected={agree} onPress={() => setAgree((a) => !a)} />
          <Link href="/privacy"><T v="small">Read the privacy policy</T></Link>
          <ErrorText error={error} />
          <Button label="Create account" onPress={submit} loading={busy}
            disabled={!agree || !form.email || form.password.length < 10 || form.full_name.length < 2 ||
              (role === 'practitioner' && !form.registration_number)} />
        </Card>
        <T v="muted">Already registered? <Link href="/sign-in"><T style={{ fontWeight: '700' }}>Sign in</T></Link></T>
      </View>
    </Screen>
  );
}
