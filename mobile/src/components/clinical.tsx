import { Linking, View } from 'react-native';

import type { Assessment, DifferentialItem, DoshaProfile } from '@/lib/types';
import { DESHA_LABEL, DOSHA_ORDER, RITU_LABEL, pretty, space, usePalette } from '@/lib/theme';

import { Bar, Card, Chip, KV, Notice, Row, T } from './ui';

export function DoshaBars({ title, profile, note }: { title: string; profile?: DoshaProfile | null; note?: string }) {
  const c = usePalette();
  if (!profile) {
    return <Card title={title}><T v="muted">{note ?? 'Not assessed yet.'}</T></Card>;
  }
  return (
    <Card title={title} right={<T v="h3">{pretty(profile.dominant)}</T>}>
      {DOSHA_ORDER.map((d) => (
        <Bar key={d} label={pretty(d)} value={profile.shares[d]} color={c[d]} />
      ))}
      {note && <T v="small">{note}</T>}
    </Card>
  );
}

export function TriageBanner({ a }: { a: Assessment }) {
  if (a.triage.level === 'routine') return null;
  const emergency = a.triage.level === 'emergency';
  return (
    <Notice tone={emergency ? 'critical' : 'warning'}>
      <T v="h3">{emergency ? 'Seek emergency care now' : 'Needs prompt medical review'}</T>
      {a.triage.flags.map((f) => (
        <T key={f.code}>• {f.advice}</T>
      ))}
      {emergency && (
        <Row>
          <Chip label="Call 112" onPress={() => Linking.openURL('tel:112')} />
          <Chip label="Ambulance 108" onPress={() => Linking.openURL('tel:108')} />
          {a.triage.flags.some((f) => f.code === 'self_harm') && (
            <Chip label="Tele-MANAS 14416" onPress={() => Linking.openURL('tel:14416')} />
          )}
        </Row>
      )}
    </Notice>
  );
}

export function KalaDeshaCard({ a }: { a: Assessment }) {
  const c = usePalette();
  const kd = a.kala_desha;
  if (!kd) return null;
  return (
    <Card title="Kala · Desha (season & habitat)">
      <KV items={[
        ['Ritu', RITU_LABEL[kd.ritu] ?? kd.ritu],
        ['Desha', kd.desha ? DESHA_LABEL[kd.desha] : 'Set your location in Profile'],
        ['Agni', a.agni ? pretty(a.agni) : '—'],
        ['Ama', a.ama ? pretty(a.ama.level) : '—'],
      ]} />
      <T v="small">{kd.ritu_info}</T>
      <Row>
        {DOSHA_ORDER.map((d) => (
          <View key={d} style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
            <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: c[d] }} />
            <T v="small">{pretty(d)}: {kd.dosha_states[d]}</T>
          </View>
        ))}
      </Row>
    </Card>
  );
}

const FACTOR_LABEL: Record<string, string> = {
  prior: 'base rate', age: 'age fit', sex: 'sex fit', vikriti: 'dosha match', prakriti: 'constitution',
  season: 'season',
};

export function DifferentialList({ items, dense = false, onSelect, selectedId }: {
  items: DifferentialItem[]; dense?: boolean; onSelect?: (d: DifferentialItem) => void; selectedId?: string | null;
}) {
  const c = usePalette();
  return (
    <View style={{ gap: space.sm }}>
      {items.map((d, i) => (
        <View key={d.condition_id}
          style={{ borderBottomWidth: i < items.length - 1 ? 1 : 0, borderColor: c.border, paddingBottom: space.sm,
            backgroundColor: selectedId === d.condition_id ? c.accentSoft : 'transparent', borderRadius: 4, padding: 2 }}>
          <Row style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
            <View style={{ flex: 1 }}>
              <T v="h3" numberOfLines={1}>{i + 1}. {d.name}</T>
              <T v="small" numberOfLines={1}>
                {[d.modern_equivalent !== d.name ? d.modern_equivalent : null,
                  d.body_system !== 'unspecified' ? pretty(d.body_system) : null,
                  d.dosha ? pretty(d.dosha) : null, d.namc ? `NAMC ${d.namc.code}` : null].filter(Boolean).join(' · ')}
              </T>
            </View>
            {onSelect && <Chip label={selectedId === d.condition_id ? 'Selected' : 'Select'} selected={selectedId === d.condition_id}
              onPress={() => onSelect(d)} />}
          </Row>
          <Bar label="Relative likelihood" value={d.likelihood} color={c.accent} />
          <Row>
            {d.evidence.supporting.map((s) => <Chip key={s} label={s} tone="yes" />)}
            {d.evidence.reported_absent_but_typical.map((s) => <Chip key={s} label={s} tone="no" />)}
          </Row>
          {dense && (
            <>
              {d.evidence.typical_not_yet_asked.length > 0 && (
                <T v="small">Typical, not asked: {d.evidence.typical_not_yet_asked.join(', ')}</T>
              )}
              <T v="mono">
                {Object.entries(d.evidence.factors).map(([k, v]) => `${FACTOR_LABEL[k] ?? k} ${v >= 0 ? '+' : ''}${v.toFixed(2)}`).join('  ')}
              </T>
              {d.prevalence && (
                <T v="small">Orphanet: {d.prevalence.orphanet_name} — {d.prevalence.class} ({d.prevalence.geography})</T>
              )}
            </>
          )}
        </View>
      ))}
    </View>
  );
}

export function AssessmentSummary({ a, dense = false }: { a: Assessment; dense?: boolean }) {
  return (
    <View style={{ gap: space.md }}>
      <TriageBanner a={a} />
      {a.stopped ? null : (
        <>
          <Card title="Possible conditions">
            {a.differential && a.differential.length > 0
              ? <DifferentialList items={a.differential.slice(0, dense ? 10 : 5)} dense={dense} />
              : <T v="muted">Add symptoms to see possible conditions.</T>}
            <T v="small">{a.disclaimer}</T>
          </Card>
        </>
      )}
    </View>
  );
}
