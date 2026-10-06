import { Ionicons } from '@expo/vector-icons';
import { Link, router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, View, useWindowDimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { WIDE } from '@/components/nav';
import { Button, Card, ErrorText, Field, Notice, Row, T } from '@/components/ui';
import { useSession } from '@/lib/session';
import { DOSHA_ORDER, radius, space, usePalette } from '@/lib/theme';

const FEATURES: [keyof typeof Ionicons.glyphMap, string, string][] = [
  ['shield-checkmark-outline', 'Safety first', '12-point emergency check before anything else'],
  ['body-outline', 'Prakriti · Vikriti', 'your constitution and current imbalance, explained'],
  ['git-network-outline', 'Reasoned screening', '1,400+ conditions ranked with the evidence for each'],
  ['medkit-outline', 'Practitioner-reviewed', 'a verified Vaidya confirms every diagnosis'],
];

export default function SignIn() {
  const c = usePalette();
  const { width } = useWindowDimensions();
  const wide = width >= WIDE;
  const { signIn } = useSession();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const submit = async () => {
    if (!email || !password) return;
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

  const form = (
    <View style={{ maxWidth: 420, width: '100%', alignSelf: 'center', gap: space.md }}>
      {!wide && <Brand compact />}
      <T v="h2">Sign in</T>
      <Card>
        <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none"
          keyboardType="email-address" autoComplete="email" textContentType="emailAddress" />
        <Field label="Password" value={password} onChangeText={setPassword} secureTextEntry
          autoComplete="password" textContentType="password" onSubmitEditing={submit} />
        <ErrorText error={error} />
        <Button label="Sign in" icon="log-in-outline" onPress={submit} loading={busy} disabled={!email || !password} />
      </Card>
      <T v="muted">New here? <Link href="/register"><T style={{ fontWeight: '700', color: c.accent }}>Create an account</T></Link></T>
      <Notice tone="warning">
        <T v="small">Not for emergencies. If you have chest pain, trouble breathing or signs of stroke, call 112 / 108.</T>
      </Notice>
      <Link href="/privacy"><T v="small">Privacy policy</T></Link>
    </View>
  );

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={{ flex: 1, flexDirection: wide ? 'row' : 'column' }}>
        {wide && (
          <View style={{ flex: 1, maxWidth: 560, backgroundColor: c.surface, borderRightWidth: 1, borderRightColor: c.border,
            padding: space.xl * 2, justifyContent: 'center', gap: space.xl }}>
            <Brand />
            <View style={{ gap: space.lg }}>
              {FEATURES.map(([icon, title, text]) => (
                <Row key={title} style={{ flexWrap: 'nowrap', alignItems: 'flex-start', gap: space.md }}>
                  <View style={{ width: 34, height: 34, borderRadius: radius + 2, alignItems: 'center', justifyContent: 'center',
                    backgroundColor: c.accentSoft }}>
                    <Ionicons name={icon} size={18} color={c.accent} />
                  </View>
                  <View style={{ flexShrink: 1 }}>
                    <T v="h3">{title}</T>
                    <T v="muted">{text}</T>
                  </View>
                </Row>
              ))}
            </View>
            <T v="small">Screening and decision support - not a diagnosis. Your data is consent-based under the DPDP Act 2023.</T>
          </View>
        )}
        <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: space.lg }}>
          {form}
        </ScrollView>
      </View>
    </SafeAreaView>
  );
}

function Brand({ compact }: { compact?: boolean }) {
  const c = usePalette();
  return (
    <View style={{ gap: space.sm }}>
      <Row style={{ gap: space.md }}>
        <View style={{ width: compact ? 36 : 44, height: compact ? 36 : 44, borderRadius: 10, backgroundColor: c.accent,
          alignItems: 'center', justifyContent: 'center' }}>
          <Ionicons name="leaf" size={compact ? 20 : 24} color={c.onAccent} />
        </View>
        <View>
          <T v="h1">Ayurnidaan</T>
          <View style={{ flexDirection: 'row', height: 3, width: 120, borderRadius: 2, overflow: 'hidden', marginTop: 2 }}>
            {DOSHA_ORDER.map((d) => <View key={d} style={{ flex: 1, backgroundColor: c[d] }} />)}
          </View>
        </View>
      </Row>
      <T v="muted">Ayurvedic screening and clinical decision support - for patients and Vaidyas.</T>
    </View>
  );
}
