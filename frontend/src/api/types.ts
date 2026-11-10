// Типы контракта API (PLAN.md, 4.4). Источник истины — app/backend/app/schemas.py.

export type StageCode = 'idea' | 'start' | 'growth';
export type ExperienceCode = 'none' | 'some' | 'experienced';
export type FormatPrefCode = 'quick' | 'template' | 'course';
export type IndustryCode =
  | 'horeca'
  | 'retail'
  | 'ecom'
  | 'services'
  | 'construction'
  | 'logistics'
  | 'b2b'
  | 'manufacturing'
  | 'wholesale'
  | 'b2g';
export type TopicCode =
  | 'taxes_law'
  | 'finance'
  | 'team'
  | 'operations'
  | 'marketing'
  | 'start'
  | 'strategy'
  | 'sales'
  | 'tech'
  | 'service'
  | 'stories'
  | 'abroad'
  | 'marketplaces';
export type EventCode = 'view' | 'start' | 'complete' | 'purchase';
export type MethodCode = 'personal' | 'baseline';
export type StatusCode = 'strong' | 'weak' | 'none' | 'cold' | 'empty';
export type FlagCode = 'in_progress' | 'completed' | 'viewed';
export type AccessCode = 'open' | 'subscription' | 'paid';

export interface HistoryEvent {
  material_id: string;
  event: EventCode;
  seq: number;
}

export interface RecommendRequest {
  task: string;
  stage: StageCode | null;
  experience: ExperienceCode | null;
  format_pref: FormatPrefCode | null;
  industry: IndustryCode | null;
  topic: TopicCode | null;
  /** null — история не передаётся; в демо-режиме сервер подставит историю профиля по profile_id */
  history: HistoryEvent[] | null;
  profile_id: string | null;
  limit: number;
  method: MethodCode;
}

export interface Option<T extends string = string> {
  label: string;
  value: T;
}

export interface Signal {
  code: string;
  label: string;
}

export interface Flag {
  code: FlagCode;
  label: string;
}

export interface Item {
  rank: number;
  material_id: string;
  title: string;
  format: string;
  format_label: string;
  topics: string[];
  topic_labels: string[];
  signals: Signal[];
  level: string | null;
  level_label: string | null;
  industries: string[];
  duration_minutes: number | null;
  access: AccessCode;
  access_label: string;
  is_paid: boolean;
  short_benefit: string | null;
  /** Есть только при link_allowed = true */
  url: string | null;
  link_allowed: boolean;
  reasons: string[];
  next_step: string;
  flags: Flag[];
  score: number;
  contributions: Record<string, number>;
}

export interface Clarification {
  question: string;
  text: string;
  field: 'topic';
  options: Option<TopicCode>[];
}

export interface RouteStep {
  material_id: string;
  title: string;
}

export interface Route {
  title: string;
  steps: RouteStep[];
}

export interface CatalogInfo {
  source: string;
  version: string;
  size: number;
  disabled_features: string[];
}

export interface RecommendResponse {
  request_id: string;
  method: MethodCode;
  catalog: CatalogInfo;
  status: StatusCode;
  detected_topics: TopicCode[];
  message: string;
  clarification: Clarification | null;
  items: Item[];
  route: Route | null;
  total_candidates: number;
}

export interface CompareResponse {
  baseline: RecommendResponse;
  personal: RecommendResponse;
  diff: { changed_positions: number; compared_positions: number };
}

export interface MetaResponse {
  topics: Option<TopicCode>[];
  stages: Option<StageCode>[];
  experience: Option<ExperienceCode>[];
  formats: Option<FormatPrefCode>[];
  industries: Option<IndustryCode>[];
  max_task_length: number;
  demo_mode: boolean;
}

export interface Profile {
  id: string;
  label: string;
  description: string;
  task: string;
  stage: StageCode | null;
  experience: ExperienceCode | null;
  format_pref: FormatPrefCode | null;
  industry: IndustryCode | null;
  history: HistoryEvent[];
}

export interface ProfilesResponse {
  profiles: Profile[];
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: { field: string; message: string }[];
  };
}
