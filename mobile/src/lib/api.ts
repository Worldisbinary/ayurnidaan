// Typed client for the Ayurnidaan clinical API with transparent access-token refresh.
import { Platform } from 'react-native';

import type {
  Assessment, AyurvedaProfile, CaseView, DailyCatalog, DailyLog, Encounter, History, IntakeOptions, Profile,
  Questionnaire, QueueItem, Tokens, Trends, User,
} from './types';

const DEFAULT_URL = Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';
export const API_URL = (process.env.EXPO_PUBLIC_API_URL || DEFAULT_URL).replace(/\/$/, '');

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type TokenHooks = {
  get: () => Tokens | null;
  set: (t: Tokens | null) => void;
};
let hooks: TokenHooks = { get: () => null, set: () => {} };
export function bindTokens(h: TokenHooks) {
  hooks = h;
}

function detail(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown })?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg).replace(/^Value error, /, '');
  return fallback;
}

let refreshing: Promise<boolean> | null = null;
async function refresh(): Promise<boolean> {
  const t = hooks.get();
  if (!t) return false;
  refreshing ??= fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: t.refresh_token }),
  })
    .then(async (r) => {
      if (!r.ok) {
        hooks.set(null);
        return false;
      }
      hooks.set(await r.json());
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function request<T>(method: string, path: string, body?: unknown, retry = true): Promise<T> {
  const t = hooks.get();
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/v1${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(t ? { Authorization: `Bearer ${t.access_token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your connection.');
  }
  if (res.status === 401 && retry && t && (await refresh())) {
    return request<T>(method, path, body, false);
  }
  if (res.status === 204) return undefined as T;
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, detail(json, `Request failed (${res.status})`));
  return json as T;
}

const get = <T>(p: string) => request<T>('GET', p);
const post = <T>(p: string, b?: unknown) => request<T>('POST', p, b ?? {});
const put = <T>(p: string, b: unknown) => request<T>('PUT', p, b);

export const api = {
  // auth
  login: (email: string, password: string) => post<Tokens>('/auth/login', { email, password }),
  register: (b: { email: string; password: string; full_name: string; role: string; registration_number?: string }) =>
    post<Tokens>('/auth/register', b),
  me: () => get<User>('/auth/me'),
  logoutAll: () => post<void>('/auth/logout-all'),

  // reference
  redFlags: () => get<{ code: string; question: string }[]>('/red-flags'),
  prakritiQuestions: () => get<{ id: string; question: string; options: string[] }[]>('/prakriti/questions'),
  intakeOptions: () => get<IntakeOptions>('/intake-options'),
  searchSymptoms: (q: string) => get<{ term: string; score: number }[]>(`/symptoms/search?q=${encodeURIComponent(q)}`),
  geoSearch: (q: string) =>
    get<{ name: string; state: string; district: string; latitude: number; longitude: number }[]>(
      `/geo/search?q=${encodeURIComponent(q)}`,
    ),
  meta: () => get<{ engine_version: string; knowledge_pack: string; counts: Record<string, number> }>('/meta'),

  // patient
  profile: () => get<Profile>('/me/profile'),
  saveProfile: (b: Partial<Profile>) => put<Profile>('/me/profile', b),
  setLocation: (b: { latitude: number; longitude: number; state?: string; district?: string }) =>
    put<Profile>('/me/location', b),
  consents: () => get<{ policy_version: string; consents: Record<string, boolean> }>('/me/consents'),
  setConsent: (purpose: string, granted: boolean) =>
    post<{ consents: Record<string, boolean> }>('/me/consents', { purpose, granted }),
  savePrakriti: (answers: Record<string, string>) => post<Profile['prakriti']>('/me/prakriti', { answers }),
  history: () => get<History>('/me/history'),
  exportData: () => get<unknown>('/me/export'),
  erase: () => request<void>('DELETE', '/me'),

  // ayurvedic profile, modules, daily tracking
  ayurveda: () => get<AyurvedaProfile>('/me/ayurveda'),
  trends: () => get<Trends>('/me/trends'),
  questionnaires: () => get<Questionnaire[]>('/questionnaires'),
  submitModule: (id: string, answers: Record<string, string | number>) =>
    post<Record<string, unknown>>(`/me/modules/${id}`, { answers }),
  dailyCatalog: () => get<DailyCatalog>('/daily/catalog'),
  daily: (days = 14) => get<DailyLog[]>(`/me/daily?days=${days}`),
  saveDaily: (day: string, body: { dinacharya: Record<string, boolean>; meals: Record<string, string[]> }) =>
    put<DailyLog>(`/me/daily/${day}`, body),
  digilockerStatus: () => get<{ mode: 'disabled' | 'sandbox' | 'production' }>('/digilocker/status'),
  digilockerStart: (return_to: string) =>
    post<{ authorize_url: string; mode: string }>('/me/digilocker/start', { return_to }),

  // encounters
  createEncounter: (b: {
    red_flag_checklist: Record<string, boolean>;
    chief_complaint?: string;
    symptoms: Record<string, boolean>;
    free_text_symptoms: string[];
    aggravating: string[];
    relieving: string[];
    agni?: string | null;
  }) => post<Encounter>('/encounters', b),
  answer: (id: string, symptoms: Record<string, boolean>, free_text_symptoms: string[] = []) =>
    post<Encounter>(`/encounters/${id}/answers`, { symptoms, free_text_symptoms }),
  submit: (id: string) => post<Encounter>(`/encounters/${id}/submit`),
  encounters: () => get<Encounter[]>('/encounters'),
  encounter: (id: string) => get<Encounter>(`/encounters/${id}`),

  // practitioner
  queue: (status = 'submitted') => get<QueueItem[]>(`/practitioner/queue?status=${status}`),
  claim: (id: string) => post(`/practitioner/encounters/${id}/claim`),
  caseView: (id: string) => get<CaseView>(`/practitioner/encounters/${id}`),
  examine: (id: string, examination: Record<string, string>) =>
    post<Encounter>(`/practitioner/encounters/${id}/examination`, { examination }),
  review: (id: string, b: { decision: string; condition_id?: string | null; notes?: string; plan?: string }) =>
    post<Encounter>(`/practitioner/encounters/${id}/review`, b),
  insights: () => get<Record<string, unknown>>('/practitioner/insights'),

  // admin
  pendingPractitioners: () =>
    get<{ id: string; full_name: string; email: string; registration_number: string; created_at: string }[]>(
      '/admin/practitioners',
    ),
  verify: (id: string, approve = true) => post(`/admin/practitioners/${id}/verify?approve=${approve}`),
  learning: () => get<{ active_version: string; eligible_cases: number; versions: unknown[] }>('/admin/learning'),
  retrain: () => post<{ promoted: boolean; reason?: string; version?: string }>('/admin/learning/retrain'),
  audit: () => get<{ at: string; actor: string; action: string; entity: string; entity_id: string }[]>('/admin/audit'),
};

export type { Assessment };
