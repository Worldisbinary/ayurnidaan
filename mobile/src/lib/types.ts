// Mirrors the FastAPI response models (src/ayurnidaan/app). Keep in sync with the API.

export type Role = 'patient' | 'practitioner' | 'admin';
export type Dosha = 'vata' | 'pitta' | 'kapha';
export type Shares = Record<Dosha, number>;
export type TriageLevel = 'emergency' | 'urgent' | 'routine';

export interface Tokens {
  access_token: string;
  refresh_token: string;
  role: Role;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  practitioner_verified: boolean;
}

export interface DoshaProfile {
  shares: Shares;
  dominant: string;
  answered: number;
  evidence: Record<Dosha, { item: string; weight: number }[]>;
}

export interface Profile {
  date_of_birth: string | null;
  sex: 'female' | 'male' | null;
  state: string | null;
  district: string | null;
  desha: 'jangala' | 'anupa' | 'sadharana' | null;
  climate: { annual_precip_mm: number; mean_rh: number; mean_temp_c: number } | null;
  prakriti: DoshaProfile | null;
  prakriti_answers: Record<string, string> | null;
  chronic_conditions: string[];
  current_medicines: string[];
  location_cell: [number, number] | null;
}

export interface DifferentialItem {
  condition_id: string;
  name: string;
  modern_equivalent: string;
  body_system: string;
  dosha: string | null;
  namc: { code: string; term: string; tier: string } | null;
  prognosis: string | null;
  prevalence: { orphanet_name: string; class: string; geography: string; weight: number } | null;
  likelihood: number;
  evidence: {
    supporting: string[];
    reported_absent_but_typical: string[];
    unexplained: string[];
    typical_not_yet_asked: string[];
    factors: Record<string, number>;
  };
}

export interface Assessment {
  engine_version: string;
  triage: { level: TriageLevel; flags: { code: string; level: string; advice: string }[] };
  stopped: boolean;
  disclaimer: string;
  free_text_mapping: { input: string; matched: string | null }[];
  prakriti?: DoshaProfile | null;
  vikriti?: DoshaProfile | null;
  agni?: string | null;
  ama?: { level: 'low' | 'moderate' | 'high'; signs: string[] };
  kala_desha?: {
    ritu: string;
    ritu_info: string;
    dosha_states: Record<Dosha, string>;
    desha: string | null;
    desha_info: string | null;
  };
  differential?: DifferentialItem[];
  next_questions?: { symptom: string; information_gain_bits: number }[];
  guidance?: { season: string[]; balance: string[]; note: string };
}

export interface ReviewOut {
  decision: 'confirmed' | 'revised' | 'ruled_out' | 'referred';
  condition_id: string | null;
  condition_name: string | null;
  notes: string | null;
  plan: string | null;
  created_at: string;
}

export interface Encounter {
  id: string;
  status: 'draft' | 'submitted' | 'reviewed' | 'emergency';
  triage_level: TriageLevel;
  chief_complaint: string | null;
  created_at: string;
  ritu: string | null;
  desha: string | null;
  engine_version: string | null;
  assessment: Assessment | null;
  reviews: ReviewOut[];
  inputs?: {
    age: number | null;
    sex: string | null;
    symptoms: Record<string, boolean>;
    examination: Record<string, string>;
    aggravating: string[];
    relieving: string[];
    agni: string | null;
  };
}

export interface History {
  encounters: {
    encounter_id: string;
    date: string;
    ritu: string | null;
    status: string;
    triage: TriageLevel;
    label: string | null;
    confirmed: boolean;
    vikriti: Shares | null;
  }[];
  recurring: { condition: string; episodes: number; ritus: Record<string, number> }[];
  seasonal_recurrence: { condition: string; episodes: number; ritus: Record<string, number> }[];
  vikriti_trend: Shares | null;
}

export interface QueueItem {
  id: string;
  created_at: string;
  triage_level: TriageLevel;
  chief_complaint: string | null;
  assigned_to_me: boolean;
  patient: { name: string | null; sex: string | null; age: number | null; desha: string | null };
  top_condition: string | null;
  top_likelihood: number | null;
  vikriti: string | null;
  ritu: string | null;
  n_symptoms: number;
}

export interface ConditionReference {
  practitioner_reference: Record<string, string>;
  patient_guidance: Record<string, string>;
  literature: { hits_all: number; hits_india: number; hits_ayurveda: number; regional_weight: number } | null;
  papers: { title: string; year: string; journal: string; cited_by: number; url: string }[];
  typical_symptoms: string[];
  age: [number, number];
  sex_weight: { female: number; male: number };
}

export interface CaseView {
  encounter: Encounter;
  patient: { name: string; profile: Profile | null };
  history: History;
  condition_references: Record<string, ConditionReference>;
}

export interface IntakeOptions {
  aggravating: string[];
  relieving: string[];
  agni: string[];
  examination: Record<string, string[]>;
}
