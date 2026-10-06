import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as Location from 'expo-location';
import * as Linking from 'expo-linking';
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Alert, Platform, Share, View } from 'react-native';

import { Badge, Button, Card, Chip, Columns, ErrorText, Field, KV, Loading, Notice, Row, Screen, T } from '@/components/ui';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';
import { DESHA_LABEL } from '@/lib/theme';
import type { Profile } from '@/lib/types';

const CONSENTS: [string, string, string][] = [
  ['care', 'Share with practitioners', 'Lets verified practitioners see the check-ups you choose to share.'],
  ['location', 'Use my approximate location', 'Your local climate (Desha) is part of Ayurvedic assessment. Stored rounded to about 11 km.'],
  ['research', 'Help improve the model', 'Practitioner-confirmed cases, without your name, help the screening model learn.'],
];

function confirmAction(title: string, message: string): Promise<boolean> {
  if (Platform.OS === 'web') return Promise.resolve(window.confirm(`${title}\n\n${message}`));
  return new Promise((resolve) =>
    Alert.alert(title, message, [
      { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
      { text: 'Continue', style: 'destructive', onPress: () => resolve(true) },
    ]),
  );
}

export default function ProfileScreen() {
  const qc = useQueryClient();
  const { user, signOut } = useSession();
  const profile = useQuery({ queryKey: ['profile'], queryFn: api.profile });
  const consents = useQuery({ queryKey: ['consents'], queryFn: api.consents });
  const modules = useQuery({ queryKey: ['questionnaires'], queryFn: api.questionnaires });
  const dlStatus = useQuery({ queryKey: ['digilocker-status'], queryFn: api.digilockerStatus, staleTime: Infinity });
  const { digilocker } = useLocalSearchParams<{ digilocker?: string }>();
  const [place, setPlace] = useState('');
  const [places, setPlaces] = useState<Awaited<ReturnType<typeof api.geoSearch>>>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      await qc.invalidateQueries({ queryKey: ['profile'] });
      await qc.invalidateQueries({ queryKey: ['consents'] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const useDeviceLocation = () => run('gps', async () => {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') throw new Error('Location permission denied. You can search for your town instead.');
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Low });
    await api.setLocation({ latitude: pos.coords.latitude, longitude: pos.coords.longitude });
  });

  if (profile.isLoading || consents.isLoading) return <Screen><Loading /></Screen>;
  const p = profile.data!;
  const c = consents.data!.consents;

  return (
    <Screen>
      <T v="h1">Profile</T>
      {digilocker === 'ok' && <Notice><T>✓ Details filled from DigiLocker.</T></Notice>}
      {digilocker && digilocker !== 'ok' && <Notice tone="warning"><T>DigiLocker was not linked ({digilocker}).</T></Notice>}
      <ErrorText error={error} />
      <Columns min={380}>
        <AboutYou key={p.date_of_birth ?? 'new'} profile={p} busy={busy === 'profile'}
          onSave={(b) => run('profile', () => api.saveProfile(b))} />

        <Card title="Consents (you can change these any time)">
          {CONSENTS.map(([key, label, help]) => (
            <Row key={key} style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
              <T style={{ flex: 1 }}>{label}{'\n'}<T v="small">{help}</T></T>
              <Chip label={c[key] ? 'On' : 'Off'} selected={!!c[key]}
                onPress={() => run(`consent-${key}`, () => api.setConsent(key, !c[key]))} />
            </Row>
          ))}
          <T v="small">Policy version {consents.data!.policy_version}</T>
        </Card>

        <Card title="Location → Desha">
          <KV items={[
            ['Desha', p.desha ? DESHA_LABEL[p.desha] : 'Not set'],
            ['Climate', p.climate ? `${Math.round(p.climate.annual_precip_mm)} mm rain · ${p.climate.mean_rh}% RH · ${p.climate.mean_temp_c}°C` : '—'],
          ]} />
          {!c.location ? <T v="small">Turn on “Use my approximate location” above first.</T> : (
            <>
              <Button label="Use my current location" icon="locate" variant="secondary" onPress={useDeviceLocation} loading={busy === 'gps'} />
              <Row>
                <Field label="…or search your town" value={place} onChangeText={setPlace} />
                <Button label="Search" compact variant="secondary" onPress={() => run('geo', async () => setPlaces(await api.geoSearch(place)))} />
              </Row>
              {places.map((pl) => (
                <Chip key={`${pl.latitude},${pl.longitude}`} label={`${pl.name}, ${pl.district ?? ''} ${pl.state ?? ''}`}
                  onPress={() => run('geo-set', async () => {
                    await api.setLocation({ latitude: pl.latitude, longitude: pl.longitude, state: pl.state, district: pl.district });
                    setPlaces([]);
                  })} />
              ))}
            </>
          )}
        </Card>

        {dlStatus.data && dlStatus.data.mode !== 'disabled' && (
          <Card title="Fill from DigiLocker" right={dlStatus.data.mode === 'sandbox' ? <Badge status="Sandbox" /> : undefined}>
            <T v="muted">Share your name, date of birth, sex and district from DigiLocker instead of typing them.
              Your Aadhaar number and documents are never stored.</T>
            {dlStatus.data.mode === 'sandbox' && <T v="small">Sandbox mode: returns a test identity until the app is approved as a DigiLocker partner.</T>}
            <Button label="Continue with DigiLocker" icon="shield-checkmark-outline" loading={busy === 'digilocker'}
              onPress={() => run('digilocker', async () => {
                if (Platform.OS === 'web') {
                  const { authorize_url } = await api.digilockerStart(`${window.location.origin}/profile`);
                  window.location.assign(authorize_url);
                  return;
                }
                const back = Linking.createURL('profile');
                const { authorize_url } = await api.digilockerStart(back);
                await WebBrowser.openAuthSessionAsync(authorize_url, back);
              })} />
          </Card>
        )}

        <Card title="Assessment modules (optional)">
          <T v="small">Each one deepens your Ayurvedic profile. Answer again any time.</T>
          {modules.data?.map((m) => (
            <Row key={m.id} style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
              <View style={{ flex: 1 }}>
                <T>{m.title}</T>
                <T v="small">{m.completed_at ? `Done ${new Date(m.completed_at).toLocaleDateString()}` : `${m.questions.length} questions`}</T>
              </View>
              <Chip label={m.completed_at ? 'Redo' : 'Start'} selected={!m.completed_at}
                onPress={() => router.push(`/(patient)/module/${m.id}`)} />
            </Row>
          ))}
        </Card>

        <Card title="Prakriti">
          <T v="muted">{p.prakriti ? `Current result: ${p.prakriti.dominant}` : 'Not assessed yet.'}</T>
          <Button label={p.prakriti ? 'Retake questionnaire' : 'Take questionnaire'} variant="secondary"
            onPress={() => router.push('/(patient)/prakriti')} />
        </Card>

        <Card title="Your data (DPDP Act)">
          <T v="small">Signed in as {user?.email}</T>
          <Button label="Export my data" icon="download-outline" variant="secondary" loading={busy === 'export'}
            onPress={() => run('export', async () => {
              const data = JSON.stringify(await api.exportData(), null, 2);
              if (Platform.OS === 'web') {
                const url = URL.createObjectURL(new Blob([data], { type: 'application/json' }));
                const a = document.createElement('a');
                a.href = url;
                a.download = 'ayurnidaan-export.json';
                a.click();
              } else {
                await Share.share({ message: data, title: 'Ayurnidaan data export' });
              }
            })} />
          <Button label="Sign out on all devices" variant="secondary" onPress={() => run('logout', async () => {
            await api.logoutAll();
            await signOut();
          })} />
          <Button label="Sign out" variant="ghost" onPress={signOut} />
          <Button label="Delete my account and data" variant="danger" loading={busy === 'erase'}
            onPress={async () => {
              if (await confirmAction('Delete account?', 'This permanently deletes your account, check-ups and reviews. It cannot be undone.')) {
                await run('erase', async () => {
                  await api.erase();
                  await signOut();
                });
              }
            }} />
        </Card>
      </Columns>
    </Screen>
  );
}

/** Form state is initialised from the loaded profile (no effect needed to sync it). */
function AboutYou({ profile, busy, onSave }: { profile: Profile; busy: boolean; onSave: (b: Partial<Profile>) => void }) {
  const [form, setForm] = useState({
    date_of_birth: profile.date_of_birth ?? '', sex: (profile.sex ?? '') as '' | 'female' | 'male',
    state: profile.state ?? '', district: profile.district ?? '',
  });
  return (
    <Card title="About you">
      <Field label="Date of birth (YYYY-MM-DD)" value={form.date_of_birth} placeholder="1990-05-21"
        onChangeText={(v) => setForm((f) => ({ ...f, date_of_birth: v }))} />
      <Row>
        <T v="label">Sex</T>
        {(['female', 'male'] as const).map((s) => (
          <Chip key={s} label={s} selected={form.sex === s} onPress={() => setForm((f) => ({ ...f, sex: s }))} />
        ))}
      </Row>
      <Row>
        <Field label="State" value={form.state} onChangeText={(v) => setForm((f) => ({ ...f, state: v }))} />
        <Field label="District" value={form.district} onChangeText={(v) => setForm((f) => ({ ...f, district: v }))} />
      </Row>
      <Button label="Save" loading={busy} onPress={() => onSave({
        date_of_birth: form.date_of_birth || null, sex: form.sex || null,
        state: form.state || null, district: form.district || null,
      })} />
    </Card>
  );
}
