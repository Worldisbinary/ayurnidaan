// Ayurvedic profile panels. Every state carries a text label (never colour alone);
// dosha identity uses the validated categorical slots, magnitudes the sequential ramp.
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { View, useColorScheme } from 'react-native';

import type { AyurvedaProfile, Derived, Dosha, Trends } from '@/lib/types';
import { DESHA_LABEL, DOSHA_ORDER, RITU_LABEL, SEQ_DARK, SEQ_LIGHT, pretty, space, usePalette } from '@/lib/theme';

import { Bar, Button, Card, Chip, KV, Row, T } from './ui';

function Dot({ dosha }: { dosha: Dosha }) {
  const c = usePalette();
  return <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: c[dosha] }} />;
}

export function CompletenessCard({ c: comp }: { c: AyurvedaProfile['completeness'] }) {
  const c = usePalette();
  const next = comp.items.filter((i) => !i.done);
  return (
    <Card title="Assessment completeness" right={<T v="h3">{comp.score}%</T>}>
      <Bar label="Profile depth" value={comp.score / 100} color={c.accent} />
      {next.length === 0 ? <T v="small">Your Ayurvedic profile is complete.</T> : (
        <>
          <T v="small">Each module sharpens your assessment:</T>
          <Row>
            {next.map((i) => (
              <Chip key={i.id} label={`+ ${i.label}`} onPress={() => router.push(linkFor(i.id))} />
            ))}
          </Row>
        </>
      )}
    </Card>
  );
}

function linkFor(id: string): '/(patient)/profile' | '/(patient)/today' | '/(patient)/check' | `/(patient)/module/${string}` {
  if (id === 'identity' || id === 'location') return '/(patient)/profile';
  if (id === 'dinacharya') return '/(patient)/today';
  if (id === 'checkup') return '/(patient)/check';
  if (id === 'prakriti') return '/(patient)/module/prakriti_quick';
  return `/(patient)/module/${id}`;
}

export function VayaKalaCard({ p }: { p: AyurvedaProfile }) {
  const c = usePalette();
  return (
    <Card title="Vaya · Desha · Kala">
      <KV items={[
        ['Life stage (Vaya)', p.vaya ? `${pretty(p.vaya.stage)} · ${pretty(p.vaya.dosha)} phase` : 'Add date of birth'],
        ['Habitat (Desha)', p.desha.desha ? DESHA_LABEL[p.desha.desha] : 'Set location'],
        ['Season (Ritu)', RITU_LABEL[p.kala.ritu] ?? p.kala.ritu],
      ]} />
      {p.vaya && <T v="small">{p.vaya.note}</T>}
      <Row>
        {DOSHA_ORDER.map((d) => (
          <Row key={d}><Dot dosha={d} /><T v="small">{pretty(d)}: {p.kala.dosha_states[d]}</T></Row>
        ))}
      </Row>
      <T v="label">Coming seasons (Ritu sandhi)</T>
      {p.kala.upcoming.map((u) => (
        <View key={u.starts} style={{ borderLeftWidth: 2, borderColor: c.border, paddingLeft: space.sm }}>
          <T style={{ fontWeight: '600' }}>{RITU_LABEL[u.ritu] ?? u.ritu} · in {u.days_away} days</T>
          <T v="small">{u.info}</T>
        </View>
      ))}
    </Card>
  );
}

export function DoshaClockCard({ clock }: { clock: AyurvedaProfile['dosha_clock'] }) {
  const c = usePalette();
  return (
    <Card title="Dosha clock (Kala)">
      <View style={{ flexDirection: 'row', gap: 2 }}>
        {clock.schedule.map((s) => {
          const now = s.span === clock.span;
          return (
            <View key={s.span} style={{ flex: 1, alignItems: 'center', paddingVertical: 6, borderRadius: 4,
              backgroundColor: now ? c[s.dosha] : c.surfaceAlt }}>
              <T v="small" style={{ color: now ? '#fff' : c.textMuted, fontWeight: now ? '700' : '400' }}>
                {pretty(s.dosha)}
              </T>
              <T v="small" style={{ fontSize: 10, color: now ? '#fff' : c.textFaint }}>{s.span.replace(':00', '').replace(':00', '')}</T>
            </View>
          );
        })}
      </View>
      <T v="small">Now: {pretty(clock.current)} period ({clock.span}). Symptoms that peak at the same time
        point to that dosha.</T>
    </Card>
  );
}

export function GunaCard({ manas, readOnly }: { manas: AyurvedaProfile['manas_prakriti']; readOnly?: boolean }) {
  const c = usePalette();
  if (!manas) {
    return (
      <Card title="Manas Prakriti · mind">
        <T v="muted">Sattva, Rajas and Tamas - the qualities of the mind.{readOnly ? ' Not answered yet.' : ''}</T>
        {!readOnly && <Button label="Take 10 questions" variant="secondary" compact onPress={() => router.push('/(patient)/module/manas_prakriti')} />}
      </Card>
    );
  }
  return (
    <Card title="Manas Prakriti · mind" right={<T v="h3">{pretty(manas.dominant)}</T>}>
      {(['sattva', 'rajas', 'tamas'] as const).map((g) => (
        <Bar key={g} label={pretty(g)} value={manas.guna_shares[g]} color={c[g]} />
      ))}
      <T v="small">{manas.note}</T>
    </Card>
  );
}

export function AgniCard({ p, readOnly }: { p: AyurvedaProfile; readOnly?: boolean }) {
  const m = p.agni_mala;
  return (
    <Card title="Agni · Koshtha · Mala · Ama">
      <KV items={[
        ['Agni (digestive fire)', pretty(m?.agni ?? p.agni_latest) || '—'],
        ['Koshtha (bowel nature)', pretty(m?.koshtha) || '—'],
        ['Aharashakti (capacity)', pretty(m?.aharashakti) || '—'],
        ['Stool (Purisha)', pretty(m?.mala.stool) || '—'],
        ['Urine (Mutra)', pretty(m?.mala.urine) || '—'],
        ['Sweat (Sweda)', pretty(m?.mala.sweat) || '—'],
        ['Ama (toxins)', p.ama ? `${pretty(p.ama.level)}${p.ama.signs.length ? ` · ${p.ama.signs.join(', ')}` : ''}` : '—'],
      ]} />
      {!m && !readOnly && <Button label="Answer 6 questions" variant="secondary" compact onPress={() => router.push('/(patient)/module/agni_mala')} />}
    </Card>
  );
}

export function OjasCard({ p, readOnly }: { p: AyurvedaProfile; readOnly?: boolean }) {
  const c = usePalette();
  const o = p.ojas;
  return (
    <Card title="Ojas · Bala (vitality)" right={o?.ojas_score != null ? <T v="h3">{o.ojas_score}/100</T> : undefined}>
      {o?.ojas_score != null ? (
        <>
          <Bar label={`Bala: ${pretty(o.bala)}`} value={o.ojas_score / 100} color={c.good} />
          <KV items={[['Exercise capacity', pretty(o.vyayamashakti) || '—'],
            ['Body measure (Pramana)', p.dashavidha?.bmi ? `BMI ${p.dashavidha.bmi} · ${pretty(p.dashavidha.pramana)}` : '—']]} />
        </>
      ) : readOnly ? <T v="muted">Not answered yet.</T> : (
        <Button label="Check your Ojas (6 questions)" variant="secondary" compact onPress={() => router.push('/(patient)/module/ojas_bala')} />
      )}
    </Card>
  );
}

const STATE_ICON = { kshaya: 'arrow-down', vriddhi: 'arrow-up', mixed: 'swap-vertical', normal: 'ellipse-outline' } as const;

export function DhatuCard({ derived }: { derived: Derived | null }) {
  const c = usePalette();
  if (!derived) return <Card title="Sapta Dhatu (7 tissues)"><T v="muted">Appears after your first check-up.</T></Card>;
  const tone = { kshaya: c.serious, vriddhi: c.warning, mixed: c.critical, normal: c.good };
  return (
    <Card title="Sapta Dhatu (7 tissues)">
      {derived.dhatus.map((d) => (
        <Row key={d.name} style={{ justifyContent: 'space-between', flexWrap: 'nowrap' }}>
          <View style={{ flex: 1 }}>
            <T style={{ fontWeight: '600' }}>{pretty(d.name)} <T v="small">· {d.nourishes}</T></T>
            {(d.kshaya_signs.length > 0 || d.vriddhi_signs.length > 0) && (
              <T v="small">{[...d.kshaya_signs, ...d.vriddhi_signs].join(', ')}</T>
            )}
          </View>
          <Row>
            <Ionicons name={STATE_ICON[d.state]} size={13} color={tone[d.state]} />
            <T v="small" style={{ color: tone[d.state], fontWeight: '700' }}>
              {d.state === 'kshaya' ? 'Depleted' : d.state === 'vriddhi' ? 'Increased' : d.state === 'mixed' ? 'Mixed' : 'Normal'}
            </T>
          </Row>
        </Row>
      ))}
      <T v="small">{derived.basis}</T>
    </Card>
  );
}

export function SrotasCard({ derived }: { derived: Derived | null }) {
  const c = usePalette();
  if (!derived) return <Card title="Srotas (body channels)"><T v="muted">Appears after your first check-up.</T></Card>;
  const involved = derived.srotas.filter((s) => s.involved).length;
  return (
    <Card title="Srotas (body channels)" right={<T v="small">{involved} of {derived.srotas.length} involved</T>}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 4 }}>
        {derived.srotas.map((s) => (
          <View key={s.name} accessibilityLabel={`${s.name} ${s.involved ? 'involved' : 'clear'}`}
            style={{ width: '32%', minWidth: 96, padding: 6, borderRadius: 4, borderWidth: 1,
              borderColor: s.involved ? c.serious : c.border, backgroundColor: s.involved ? c.warningSoft : c.surface }}>
            <Row style={{ flexWrap: 'nowrap' }}>
              <Ionicons name={s.involved ? 'alert-circle' : 'checkmark-circle-outline'} size={12}
                color={s.involved ? c.serious : c.textFaint} />
              <T v="small" style={{ fontWeight: '700', color: s.involved ? c.text : c.textMuted }}>{pretty(s.name)}</T>
            </Row>
            <T v="small" style={{ fontSize: 10 }} numberOfLines={2}>{s.involved ? s.matched.join(', ') : s.carries}</T>
          </View>
        ))}
      </View>
    </Card>
  );
}

export function SubdoshaCard({ derived }: { derived: Derived | null }) {
  if (!derived) return null;
  return (
    <Card title="Subdoshas involved">
      {derived.subdoshas.length === 0 ? <T v="muted">No subdosha pattern from current symptoms.</T> :
        derived.subdoshas.map((s) => (
          <Row key={s.name} style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
            <View style={{ paddingTop: 5 }}><Dot dosha={s.dosha} /></View>
            <View style={{ flex: 1 }}>
              <T style={{ fontWeight: '600' }}>{pretty(s.name)} {pretty(s.dosha)} <T v="small">· {s.seat}</T></T>
              <T v="small">{s.governs} — {s.matched.join(', ')}</T>
            </View>
          </Row>
        ))}
    </Card>
  );
}

export function DinacharyaCard({ d, readOnly }: { d: AyurvedaProfile['dinacharya']; readOnly?: boolean }) {
  const c = usePalette();
  const ramp = useColorScheme() === 'dark' ? SEQ_DARK : SEQ_LIGHT;
  const days = d.window.map((day) => ({ day, score: d.days.find((x) => x.day === day)?.score }));
  return (
    <Card title="Dinacharya · last 7 days" right={<T v="small">{d.streak} day streak</T>}>
      <View style={{ flexDirection: 'row', gap: 3 }}>
        {days.map((x) => (
          <View key={x.day} style={{ flex: 1, alignItems: 'center', gap: 2 }}>
            <View accessibilityLabel={`${x.day}: ${x.score ?? 'not logged'}`}
              style={{ width: '100%', height: 30, borderRadius: 4, alignItems: 'center', justifyContent: 'center',
                backgroundColor: x.score == null ? c.surfaceAlt : ramp[Math.min(5, Math.floor(x.score / 17))] }}>
              <T v="small" style={{ color: x.score != null && x.score >= 50 ? '#fff' : c.textMuted, fontWeight: '700' }}>
                {x.score ?? '–'}
              </T>
            </View>
            <T v="small" style={{ fontSize: 10 }}>{new Date(x.day).toLocaleDateString([], { weekday: 'narrow' })}</T>
          </View>
        ))}
      </View>
      <Row style={{ justifyContent: 'space-between' }}>
        <T v="small">Average {d.average ?? '—'} / 100</T>
        {!readOnly && <Button label="Log today" compact variant="secondary" onPress={() => router.push('/(patient)/today')} />}
      </Row>
    </Card>
  );
}

export function DietCard({ diet }: { diet: AyurvedaProfile['diet'] }) {
  const c = usePalette();
  const max = Math.max(1, ...Object.values(diet.tastes));
  return (
    <Card title="Ahara · six tastes this week">
      <T v="small">Times each taste appeared in logged meals.</T>
      {Object.entries(diet.tastes).map(([t, n]) => (
        <Bar key={t} label={`${pretty(t)}${diet.favour_tastes.includes(t) ? ' ★' : ''}`} value={n / max}
          color={diet.favour_tastes.includes(t) ? c.good : c.accent} display={`${n}×`} />
      ))}
      {diet.focus_dosha && (
        <T v="small">★ Tastes that balance {pretty(diet.focus_dosha)}: {diet.favour_tastes.map(pretty).join(', ')}.</T>
      )}
      {diet.viruddha.length > 0 && (
        <View style={{ gap: 2 }}>
          <T v="label">Incompatible combinations (Viruddha ahara)</T>
          {diet.viruddha.slice(-3).map((v, i) => <T key={i} v="small">• {v.day} {v.meal}: {v.message}</T>)}
        </View>
      )}
    </Card>
  );
}

export function TrendsCard({ t }: { t: Trends | undefined }) {
  const c = usePalette();
  const rows = (t?.checkups ?? []).filter((x) => x.vikriti).slice(-8);
  return (
    <Card title="Vikriti trend across check-ups">
      {rows.length < 2 ? <T v="muted">Shows how your imbalance changes once you have two or more check-ups.</T> :
        DOSHA_ORDER.map((d) => (
          <Row key={d} style={{ flexWrap: 'nowrap' }}>
            <T v="small" style={{ width: 44 }}>{pretty(d)}</T>
            <View style={{ flex: 1, flexDirection: 'row', alignItems: 'flex-end', gap: 3, height: 26 }}>
              {rows.map((r, i) => (
                <View key={`${d}-${i}`} accessibilityLabel={`${r.date} ${d} ${Math.round((r.vikriti?.[d] ?? 0) * 100)}%`}
                  style={{ flex: 1, height: `${Math.max(4, (r.vikriti?.[d] ?? 0) * 100)}%`, backgroundColor: c[d],
                    borderTopLeftRadius: 3, borderTopRightRadius: 3 }} />
              ))}
            </View>
          </Row>
        ))}
      {rows.length >= 2 && <T v="small">{rows[0].date} → {rows[rows.length - 1].date}</T>}
    </Card>
  );
}
