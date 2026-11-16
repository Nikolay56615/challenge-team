// Типы контракта API. Источник истины — backend/app/schemas.py.
// Совпадение со схемой OpenAPI проверяет при сборке src/api/contract.ts.

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
  /** В схеме OpenAPI поле со значением по умолчанию и не обязательно; интерфейс его не читает */
  field?: 'topic';
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

/** Источник вклада в оценку ленты (app/backend/app/ranking/feed.py, SOURCES) */
export type FeedSourceCode =
  | 'progress'
  | 'history'
  | 'content'
  | 'links'
  | 'task'
  | 'profile'
  | 'access'
  | 'popularity'
  | 'seen';
export type FeedStatus = 'history' | 'cold';

export interface FeedRequest {
  task: string;
  stage: StageCode | null;
  experience: ExperienceCode | null;
  format_pref: FormatPrefCode | null;
  industry: IndustryCode | null;
  /** null — история берётся у клиента с кодом user_id */
  history: HistoryEvent[] | null;
  user_id: string | null;
  /** «Что если»: события этих материалов убираются из истории */
  exclude_history: string[];
  /** «Что если»: события добавляются после последнего события истории; seq задаёт порядок между ними */
  add_history: HistoryEvent[];
  limit: number;
  /** Вес источника «доступ и цена» от 0 до 1; null — вес сервера по умолчанию, 0 — без учёта цены */
  price_weight: number | null;
}

export interface FeedPart {
  source: FeedSourceCode;
  label: string;
  value: number;
  evidence: string | null;
  /** Как считается вклад, если его считает модель, а свидетельство называет только запись с наибольшим весом */
  note: string | null;
}

export interface FeedItem {
  rank: number;
  material_id: string;
  title: string;
  format: string;
  format_label: string;
  topic_labels: string[];
  level_label: string | null;
  duration_minutes: number | null;
  access: AccessCode;
  access_label: string;
  is_paid: boolean;
  short_benefit: string | null;
  url: string | null;
  link_allowed: boolean;
  next_step: string;
  flags: Flag[];
  /** Равна сумме parts[].value */
  score: number;
  parts: FeedPart[];
  reason: string;
}

export interface FeedHistoryEntry {
  material_id: string;
  /** null — материала нет в каталоге */
  title: string | null;
  format_label: string | null;
  event: EventCode;
  event_label: string;
}

export interface FeedShare {
  label: string;
  share: number;
}

export interface FeedSourceShare extends FeedShare {
  source: FeedSourceCode;
}

/** Поле профиля клиента и откуда оно известно: «указано в анкете», «выведено из истории», «не указано» */
export interface FeedFact {
  name: string;
  value: string | null;
  origin: string;
}

/** Клиент из подключённого журнала */
export interface User {
  id: string;
  label: string;
  /** null — у журнала нет сегментов */
  segment: string | null;
  /** Число материалов в истории */
  materials: number;
  paid: boolean;
}

/** Клиенты, код которых начинается с запроса: первые из matched; total — всего в журнале */
export interface UsersResponse {
  source: string;
  total: number;
  matched: number;
  users: User[];
}

/** Метод на журнале записей: доля пользователей, у которых скрытый курс стоит первым и в первых пяти */
export interface ModelCardRow {
  method: string;
  label: string;
  hit1: number;
  hit5: number;
  ndcg5: number;
}

export interface ModelCardGroup {
  code: string;
  label: string;
  users: number;
  rows: ModelCardRow[];
}

export interface ModelCardValue {
  label: string;
  value: number;
  /** true — значение есть доля от 0 до 1 */
  share: boolean;
}

/** Паспорт модели ленты: тип данных проверки, качество по группам, веса источников и свойства ленты */
export interface ModelCard {
  data: string;
  groups: ModelCardGroup[];
  weights: ModelCardValue[];
  feed: ModelCardValue[];
}

export interface FeedResponse {
  request_id: string;
  catalog: CatalogInfo;
  /** Клиент, по истории которого построена лента; null — история пришла в запросе */
  user: User | null;
  status: FeedStatus;
  message: string;
  items: FeedItem[];
  total_candidates: number;
  history: FeedHistoryEntry[];
  interests: FeedShare[];
  facts: FeedFact[];
  sources: FeedSourceShare[];
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: { field: string; message: string }[];
  };
}
