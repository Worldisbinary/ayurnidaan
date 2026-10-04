import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';

import { DoshaBars } from '@/components/clinical';
import { Badge, Button, Card, Columns, KV, Loading, Notice, Row, Screen, T, Table } from '@/components/ui';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';
import { DESHA_LABEL, RITU_LABEL } from '@/lib/theme';

function currentRitu(d = new Date()): string {
  const md = (d.getMonth() + 1) * 100 + d.getDate();
  if (md >= 1115) return 'hemanta';
  if (md >= 915) return 'sharad';
  if (md >= 715) return 'varsha';
  if (md >= 515) return 'grishma';
  if (md >= 315) return 'vasanta';
  if (md >= 115) return 'shishira';
  return 'hemanta';
}

export default function PatientHome() {
  const { user } = useSession();
  const profile = useQuery({ queryKey: ['profile'], queryFn: api.profile });
  const consents = useQuery({ queryKey: ['consents'], queryFn: api.consents });
  const encounters = useQuery({ queryKey: ['encounters'], queryFn: api.encounters });
  const refreshing = profile.isFetching || encounters.isFetching;
  const p = profile.data;
  const todo: [string, () => void][] = [];
  if (p && (!p.date_of_birth || !p.sex)) todo.push(['Add your date of birth and sex', () => router.push('/(patient)/profile')]);
  if (p && !p.prakriti) todo.push(['Find your Prakriti (9 questions)', () => router.push('/(patient)/prakriti')]);
  if (p && !p.desha) todo.push(['Set your location for climate (Desha)', () => router.push('/(patient)/profile')]);
  if (consents.data && !consents.data.consents.care) todo.push(['Allow sharing with practitioners', () => router.push('/(patient)/profile')]);

  return (
    <Screen onRefresh={() => { profile.refetch(); encounters.refetch(); }} refreshing={refreshing}>
      <Row style={{ justifyContent: 'space-between' }}>
        <T v="h1">Namaste, {user?.full_name.split(' ')[0]}</T>
        <Button label="New check" icon="add" onPress={() => router.push('/(patient)/check')} />
      </Row>
      {profile.isLoading ? <Loading /> : (
        <Columns>
          {todo.length > 0 && (
            <Card title="Complete your profile">
              {todo.map(([label, go]) => <Button key={label} label={label} variant="secondary" onPress={go} compact />)}
            </Card>
          )}
          <DoshaBars title="Prakriti · constitution" profile={p?.prakriti}
            note={p?.prakriti ? 'Your stable body-mind type.' : 'Answer 9 questions to find your Prakriti.'} />
          <Card title="Kala · Desha">
            <KV items={[
              ['Season (Ritu)', RITU_LABEL[currentRitu()]],
              ['Habitat (Desha)', p?.desha ? DESHA_LABEL[p.desha] : 'Not set'],
              ['Rainfall / humidity', p?.climate ? `${Math.round(p.climate.annual_precip_mm)} mm · ${p.climate.mean_rh}%` : '—'],
            ]} />
          </Card>
          <Card title="Recent check-ups">
            {encounters.data?.length ? (
              <Table head={['Date', 'Complaint', 'Status']} flex={[1, 2, 1.3]}
                rows={encounters.data.slice(0, 6).map((e) => [
                  new Date(e.created_at).toLocaleDateString(),
                  e.chief_complaint || e.assessment?.differential?.[0]?.name || '—',
                  <Badge key="b" status={e.status === 'draft' ? e.triage_level : e.status} />,
                ])}
                onRowPress={(i) => router.push(`/(patient)/encounter/${encounters.data![i].id}`)} />
            ) : <T v="muted">No check-ups yet.</T>}
          </Card>
          <Notice>
            <T v="small">Ayurnidaan suggests possible conditions to discuss with a practitioner. It is not a diagnosis.
              In an emergency call 112 / 108.</T>
          </Notice>
        </Columns>
      )}
    </Screen>
  );
}
