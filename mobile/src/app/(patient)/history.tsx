import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { View } from 'react-native';

import { Badge, Card, Columns, EmptyState, Row, Screen, SkeletonCards, T, Table } from '@/components/ui';
import { api } from '@/lib/api';
import { DOSHA_ORDER, RITU_LABEL, pretty, usePalette } from '@/lib/theme';

export default function HistoryScreen() {
  const c = usePalette();
  const q = useQuery({ queryKey: ['history'], queryFn: api.history });
  const h = q.data;
  return (
    <Screen onRefresh={() => q.refetch()} refreshing={q.isFetching}>
      <T v="h1">Health history</T>
      {q.isLoading || !h ? <SkeletonCards count={3} min={420} /> : (
        <Columns min={420}>
          <Card title={`Timeline · ${h.encounters.length} check-ups`}>
            {h.encounters.length ? (
              <Table head={['Date', 'Season', 'Finding', 'Status']} flex={[1, 1, 2, 1.3]}
                rows={[...h.encounters].reverse().map((e) => [
                  e.date, e.ritu ? pretty(e.ritu) : '—',
                  `${e.label ?? '—'}${e.confirmed ? ' ✓' : ''}`,
                  <Badge key="s" status={e.status === 'draft' ? e.triage : e.status} />,
                ])}
                onRowPress={(i) => router.push(`/(patient)/encounter/${[...h.encounters].reverse()[i].encounter_id}`)} />
            ) : (
              <EmptyState icon="time-outline" title="Your timeline starts with a check-up"
                message="Each check-up is saved here with its season, so recurring and seasonal patterns can show up over time."
                action={{ label: 'Start a check-up', icon: 'add', onPress: () => router.push('/(patient)/check') }} />
            )}
          </Card>
          <Card title="Patterns">
            {h.recurring.length === 0 && <T v="muted">No recurring conditions found yet.</T>}
            {h.recurring.map((r) => (
              <View key={r.condition} style={{ gap: 2 }}>
                <T v="h3">{r.condition} · {r.episodes} episodes</T>
                <T v="small">{Object.entries(r.ritus).map(([k, n]) => `${RITU_LABEL[k] ?? k}: ${n}`).join(' · ')}</T>
              </View>
            ))}
            {h.seasonal_recurrence.length > 0 && (
              <T>Seasonal pattern: {h.seasonal_recurrence.map((r) => r.condition).join(', ')} tends to return in the same season -
                ask your practitioner about seasonal prevention (Ritucharya).</T>
            )}
          </Card>
          <Card title="Imbalance trend (first → latest check-up)">
            {h.vikriti_trend ? DOSHA_ORDER.map((d) => {
              const delta = h.vikriti_trend![d];
              return (
                <Row key={d} style={{ justifyContent: 'space-between' }}>
                  <Row><View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: c[d] }} /><T>{pretty(d)}</T></Row>
                  <T style={{ fontVariant: ['tabular-nums'] }}>{delta >= 0 ? '▲ +' : '▼ '}{(delta * 100).toFixed(0)} pts</T>
                </Row>
              );
            }) : <T v="muted">Needs at least two check-ups.</T>}
          </Card>
        </Columns>
      )}
    </Screen>
  );
}
