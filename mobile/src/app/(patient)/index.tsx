import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { Pressable, View } from 'react-native';

import {
  AgniCard, DhatuCard, DietCard, DinacharyaCard, DoshaClockCard, GunaCard, OjasCard,
  SrotasCard, SubdoshaCard, TrendsCard, VayaKalaCard, CompletenessCard,
} from '@/components/ayurveda';
import { DoshaBars } from '@/components/clinical';
import {
  Badge, Button, Card, Columns, EmptyState, Notice, Row, Screen, SkeletonCards, StatRow, StatTile, T, Table,
} from '@/components/ui';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';
import { DOSHA_ORDER, RITU_LABEL, font, pretty, radius, space, usePalette } from '@/lib/theme';
import type { AyurvedaProfile, DoshaProfile } from '@/lib/types';

// Order a new user should go through; ids match the server's completeness items.
const START: { id: string; label: string; hint: string }[] = [
  { id: 'identity', label: 'Your details', hint: 'DigiLocker or age & sex' },
  { id: 'location', label: 'Location', hint: 'gives your Desha' },
  { id: 'prakriti', label: 'Prakriti', hint: '9 quick questions' },
  { id: 'checkup', label: 'First check-up', hint: 'symptoms → assessment' },
  { id: 'dinacharya', label: 'Daily log', hint: '30 seconds a day' },
];

export default function PatientHome() {
  const { user } = useSession();
  const profile = useQuery({ queryKey: ['ayurveda'], queryFn: api.ayurveda });
  const trends = useQuery({ queryKey: ['trends'], queryFn: api.trends });
  const encounters = useQuery({ queryKey: ['encounters'], queryFn: api.encounters });
  const p = profile.data;
  const refresh = () => { profile.refetch(); trends.refetch(); encounters.refetch(); };
  const first = user?.full_name.split(' ')[0];

  return (
    <Screen onRefresh={refresh} refreshing={profile.isRefetching}>
      {profile.isLoading || !p ? (
        <>
          <T v="h1">Namaste{first ? `, ${first}` : ''}</T>
          <SkeletonCards count={9} />
        </>
      ) : (
        <>
          <Hero p={p} name={first} />
          <GetStarted p={p} />
          <Stats p={p} lastCheck={encounters.data?.[0]?.created_at} />
          <Columns min={330}>
            <CompletenessCard c={p.completeness} />
            <DoshaBars title={`Prakriti · body${p.prakriti_source === 'full' ? ' (full)' : ''}`} profile={p.prakriti}
              note={p.prakriti ? 'Your lifelong constitution.' : 'Answer 9 questions to find your Prakriti.'} />
            <DoshaBars title={`Vikriti · now${p.vikriti_date ? ` (${p.vikriti_date})` : ''}`} profile={p.vikriti}
              note={p.vikriti ? 'Current imbalance from your latest check-up.' : 'Do a check-up to see your current imbalance.'} />
            <GunaCard manas={p.manas_prakriti} />
            <VayaKalaCard p={p} />
            <DoshaClockCard clock={p.dosha_clock} />
            <AgniCard p={p} />
            <OjasCard p={p} />
            {p.recommendations.length > 0 && (
              <Card title="For you now">
                {p.recommendations.map((r) => <T key={r}>• {r}</T>)}
                <T v="small">General wellness guidance - not a prescription.</T>
              </Card>
            )}
          </Columns>
          <Columns min={420}>
            <DhatuCard derived={p.ayurveda} />
            <SrotasCard derived={p.ayurveda} />
            <SubdoshaCard derived={p.ayurveda} />
          </Columns>
          <Columns min={330}>
            <DinacharyaCard d={p.dinacharya} />
            <DietCard diet={p.diet} />
            <TrendsCard t={trends.data} />
            <Card title="Recent check-ups">
              {encounters.data?.length ? (
                <Table head={['Date', 'Complaint', 'Status']} flex={[1, 2, 1.3]}
                  rows={encounters.data.slice(0, 5).map((e) => [
                    new Date(e.created_at).toLocaleDateString(),
                    e.chief_complaint || e.assessment?.differential?.[0]?.name || '—',
                    <Badge key="b" status={e.status === 'draft' ? e.triage_level : e.status} />,
                  ])}
                  onRowPress={(i) => router.push(`/(patient)/encounter/${encounters.data![i].id}`)} />
              ) : (
                <EmptyState icon="medkit-outline" title="No check-ups yet"
                  message="Tell us what is bothering you and get a screening in about two minutes."
                  action={{ label: 'Start a check-up', icon: 'add', onPress: () => router.push('/(patient)/check') }} />
              )}
            </Card>
          </Columns>
          <Notice>
            <T v="small">Ayurnidaan suggests possible conditions to discuss with a practitioner. It is not a diagnosis.
              Dhatu, srotas and subdosha views are textbook rules (Charaka, Ashtanga Hridaya). In an emergency call 112 / 108.</T>
          </Notice>
        </>
      )}
    </Screen>
  );
}

const doshaName = (d: DoshaProfile | null) =>
  d ? d.dominant.split(/[-_ ]/).map((x) => pretty(x)).join('-') : null;

function Hero({ p, name }: { p: AyurvedaProfile; name?: string }) {
  const c = usePalette();
  const aggravated = DOSHA_ORDER.filter((d) => p.kala.dosha_states[d] === 'prakopa');
  const today = new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
  return (
    <View style={{ borderRadius: radius + 4, borderWidth: 1, borderColor: c.border, backgroundColor: c.surface, overflow: 'hidden' }}>
      <View style={{ flexDirection: 'row', height: 4 }}>
        {DOSHA_ORDER.map((d) => <View key={d} style={{ flex: p.prakriti?.shares[d] ?? 1, backgroundColor: c[d] }} />)}
      </View>
      <View style={{ padding: space.lg, gap: space.md }}>
        <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <View style={{ gap: 4, flexShrink: 1, minWidth: 240 }}>
            <T v="small">{today}</T>
            <T v="h1">Namaste{name ? `, ${name}` : ''}</T>
            <Row style={{ gap: space.md }}>
              <Fact icon="body-outline" label="Prakriti" value={doshaName(p.prakriti) ?? 'not yet known'} />
              <Fact icon="pulse-outline" label="Vikriti now" value={doshaName(p.vikriti) ?? 'no check-up yet'} />
              <Fact icon="partly-sunny-outline" label="Season" value={RITU_LABEL[p.kala.ritu] ?? pretty(p.kala.ritu)} />
              {p.dosha_clock.current && (
                <Fact icon="time-outline" label="Dosha time" value={`${pretty(p.dosha_clock.current)} · ${p.dosha_clock.span}`} />
              )}
            </Row>
            {aggravated.length > 0 && (
              <Row style={{ marginTop: 2, flexWrap: 'nowrap', alignItems: 'flex-start' }}>
                <Ionicons name="trending-up" size={14} color={c.serious} style={{ marginTop: 1 }} />
                <T v="small" style={{ color: c.text, flexShrink: 1 }}>
                  {aggravated.map(pretty).join(' & ')} tends to aggravate this season - {
                    aggravated.some((d) => p.prakriti?.dominant.includes(d)) ? 'and it is part of your constitution, so take extra care.' : 'keep an eye on it.'}
                </T>
              </Row>
            )}
          </View>
          <Row>
            <Button label="Log today" icon="sunny-outline" variant="secondary" onPress={() => router.push('/(patient)/today')} />
            <Button label="New check-up" icon="add" onPress={() => router.push('/(patient)/check')} />
          </Row>
        </Row>
        {p.identity.verified && (
          <Row><Ionicons name="shield-checkmark" size={14} color={c.good} /><T v="small">Identity verified via DigiLocker</T></Row>
        )}
      </View>
    </View>
  );
}

function Fact({ icon, label, value }: { icon: keyof typeof Ionicons.glyphMap; label: string; value: string }) {
  const c = usePalette();
  return (
    <Row style={{ gap: 6, flexWrap: 'nowrap' }}>
      <Ionicons name={icon} size={15} color={c.textMuted} />
      <View>
        <T v="label">{label}</T>
        <T style={{ fontWeight: '600' }}>{value}</T>
      </View>
    </Row>
  );
}

function Stats({ p, lastCheck }: { p: AyurvedaProfile; lastCheck?: string }) {
  const days = lastCheck ? Math.floor((Date.parse(new Date().toISOString().slice(0, 10)) - Date.parse(lastCheck.slice(0, 10))) / 86_400_000) : null;
  const ojas = p.ojas?.ojas_score;
  const ama = p.ama?.level;
  // Latest check-up wins; otherwise the digestion module's answer.
  const agni = p.agni_latest ?? p.agni_mala?.agni ?? null;
  return (
    <StatRow>
      <StatTile label="Profile depth" value={`${p.completeness.score}%`} icon="layers-outline"
        hint={p.completeness.score >= 100 ? 'complete' : `${p.completeness.items.filter((i) => !i.done).length} modules to go`}
        tone={p.completeness.score >= 80 ? 'good' : 'accent'} />
      <StatTile label="Ojas" value={ojas != null ? `${Math.round(ojas)}` : '—'} icon="flame-outline"
        hint={ojas != null ? 'vitality score / 100' : 'take the Ojas module'}
        tone={ojas == null ? 'muted' : ojas >= 70 ? 'good' : ojas >= 45 ? 'warning' : 'critical'}
        onPress={ojas == null ? () => router.push('/(patient)/module/ojas_bala') : undefined} />
      <StatTile label="Agni" value={agni ? pretty(agni).split(' ')[0] : '—'} icon="bonfire-outline"
        hint={ama ? `Ama ${ama}` : agni ? 'digestive fire' : 'take the digestion module'}
        tone={ama === 'high' ? 'warning' : 'accent'}
        onPress={agni ? undefined : () => router.push('/(patient)/module/agni_mala')} />
      <StatTile label="Routine streak" value={`${p.dinacharya.streak} d`} icon="sunny-outline"
        hint={p.dinacharya.average != null ? `avg ${Math.round(p.dinacharya.average)} / 100` : 'log today'}
        tone={p.dinacharya.streak >= 3 ? 'good' : 'muted'} onPress={() => router.push('/(patient)/today')} />
      <StatTile label="Last check-up" value={days == null ? '—' : days === 0 ? 'Today' : `${days} d ago`} icon="medkit-outline"
        hint={days == null ? 'none yet' : 'tap for a new one'} tone="muted" onPress={() => router.push('/(patient)/check')} />
    </StatRow>
  );
}

function GetStarted({ p }: { p: AyurvedaProfile }) {
  const c = usePalette();
  const done = new Set(p.completeness.items.filter((i) => i.done).map((i) => i.id));
  const steps = START.filter((s) => p.completeness.items.some((i) => i.id === s.id));
  const remaining = steps.filter((s) => !done.has(s.id));
  if (remaining.length === 0) return null;
  const next = remaining[0];
  return (
    <Card title={`Get started · ${steps.length - remaining.length} of ${steps.length} done`}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.sm }}>
        {steps.map((s, i) => {
          const isDone = done.has(s.id);
          const isNext = s.id === next.id;
          return (
            <Pressable key={s.id} onPress={() => router.push(linkFor(s.id))} accessibilityRole="button"
              accessibilityLabel={`${s.label}${isDone ? ', done' : ''}`}
              style={({ pressed }) => ({
                flexDirection: 'row', alignItems: 'center', gap: space.sm, flexGrow: 1, flexBasis: 170,
                padding: space.md, borderRadius: radius, borderWidth: 1,
                borderColor: isNext ? c.accent : c.border, backgroundColor: isNext ? c.accentSoft : pressed ? c.surfaceAlt : c.surface,
              })}>
              <View style={{ width: 24, height: 24, borderRadius: 12, alignItems: 'center', justifyContent: 'center',
                backgroundColor: isDone ? c.good : 'transparent', borderWidth: isDone ? 0 : 1.5, borderColor: isNext ? c.accent : c.textFaint }}>
                {isDone ? <Ionicons name="checkmark" size={14} color="#fff" />
                  : <T style={{ fontSize: font.xs, fontWeight: '700', color: isNext ? c.accent : c.textFaint }}>{i + 1}</T>}
              </View>
              <View style={{ flexShrink: 1 }}>
                <T style={{ fontWeight: '600', textDecorationLine: isDone ? 'line-through' : 'none', color: isDone ? c.textMuted : c.text }}>{s.label}</T>
                <T v="small">{s.hint}</T>
              </View>
            </Pressable>
          );
        })}
      </View>
    </Card>
  );
}

function linkFor(id: string): '/(patient)/profile' | '/(patient)/today' | '/(patient)/check' | `/(patient)/module/${string}` {
  if (id === 'identity' || id === 'location') return '/(patient)/profile';
  if (id === 'dinacharya') return '/(patient)/today';
  if (id === 'checkup') return '/(patient)/check';
  return '/(patient)/module/prakriti_quick';
}

