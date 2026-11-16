/* eslint-disable */
// Создано scripts/gen-api.mjs из src/api/openapi.json. Не править вручную: npm run gen:api.
// Схема: OpenAPI 3.1.0, Подбор учебных материалов 0.1.0

/**
 * Все схемы компонентов OpenAPI по именам
 */
export interface ApiSchemas {
  CatalogInfo: CatalogInfo;
  Clarification: Clarification;
  CompareDiff: CompareDiff;
  CompareResponse: CompareResponse;
  ErrorBody: ErrorBody;
  ErrorDetail: ErrorDetail;
  ErrorResponse: ErrorResponse;
  FeedFact: FeedFact;
  FeedHistoryOut: FeedHistoryOut;
  FeedItemOut: FeedItemOut;
  FeedPart: FeedPart;
  FeedRequest: FeedRequest;
  FeedResponse: FeedResponse;
  FeedShare: FeedShare;
  FeedSourceShare: FeedSourceShare;
  FlagOut: FlagOut;
  HealthCatalog: HealthCatalog;
  HealthResponse: HealthResponse;
  HistoryEventIn: HistoryEventIn;
  HistoryEventOut: HistoryEventOut;
  ItemOut: ItemOut;
  MetaResponse: MetaResponse;
  ModelCardGroup: ModelCardGroup;
  ModelCardResponse: ModelCardResponse;
  ModelCardRow: ModelCardRow;
  ModelCardValue: ModelCardValue;
  Option: Option;
  ProbeResponse: ProbeResponse;
  ProfileOut: ProfileOut;
  ProfilesResponse: ProfilesResponse;
  RecommendRequest: RecommendRequest;
  RecommendResponse: RecommendResponse;
  Route: Route;
  RouteStep: RouteStep;
  SignalOut: SignalOut;
  UserOut: UserOut;
  UsersResponse: UsersResponse;
}
export interface CatalogInfo {
  disabled_features: string[];
  size: number;
  source: string;
  version: string;
}
export interface Clarification {
  field?: 'topic';
  options: Option[];
  question: string;
  text: string;
}
export interface Option {
  label: string;
  value: string;
}
export interface CompareDiff {
  changed_positions: number;
  compared_positions: number;
}
export interface CompareResponse {
  baseline: RecommendResponse;
  diff: CompareDiff;
  personal: RecommendResponse;
}
export interface RecommendResponse {
  catalog: CatalogInfo;
  clarification: Clarification | null;
  detected_topics: string[];
  items: ItemOut[];
  message: string;
  method: 'personal' | 'baseline';
  request_id: string;
  route: Route | null;
  status: 'strong' | 'weak' | 'none' | 'cold' | 'empty';
  total_candidates: number;
}
export interface ItemOut {
  access: 'open' | 'subscription' | 'paid';
  access_label: string;
  contributions: {
    [k: string]: number;
  };
  duration_minutes: number | null;
  flags: FlagOut[];
  format: string;
  format_label: string;
  industries: string[];
  is_paid: boolean;
  level: string | null;
  level_label: string | null;
  link_allowed: boolean;
  material_id: string;
  next_step: string;
  rank: number;
  reasons: string[];
  score: number;
  short_benefit: string | null;
  signals: SignalOut[];
  title: string;
  topic_labels: string[];
  topics: string[];
  url: string | null;
}
export interface FlagOut {
  code: 'in_progress' | 'completed' | 'viewed';
  label: string;
}
export interface SignalOut {
  code: string;
  label: string;
}
export interface Route {
  steps: RouteStep[];
  title: string;
}
export interface RouteStep {
  material_id: string;
  title: string;
}
export interface ErrorBody {
  code: string;
  details: ErrorDetail[];
  message: string;
}
export interface ErrorDetail {
  field: string;
  message: string;
}
export interface ErrorResponse {
  error: ErrorBody;
}
/**
 * Поле профиля клиента с подписью происхождения: анкета, вывод из истории или «не указано».
 */
export interface FeedFact {
  name: string;
  origin: string;
  value: string | null;
}
export interface FeedHistoryOut {
  event: 'view' | 'start' | 'complete' | 'purchase';
  event_label: string;
  format_label: string | null;
  material_id: string;
  title: string | null;
}
export interface FeedItemOut {
  access: 'open' | 'subscription' | 'paid';
  access_label: string;
  duration_minutes: number | null;
  flags: FlagOut[];
  format: string;
  format_label: string;
  is_paid: boolean;
  level_label: string | null;
  link_allowed: boolean;
  material_id: string;
  next_step: string;
  parts: FeedPart[];
  rank: number;
  reason: string;
  score: number;
  short_benefit: string | null;
  title: string;
  topic_labels: string[];
  url: string | null;
}
export interface FeedPart {
  evidence: string | null;
  label: string;
  note: string | null;
  source: 'progress' | 'history' | 'content' | 'links' | 'task' | 'profile' | 'access' | 'popularity' | 'seen';
  value: number;
}
/**
 * Запрос ленты по профилю (docs/plan.md, раздел 13).
 *
 * История берётся из `history`, а без неё — у клиента с кодом `user_id` (`GET /api/users`). Затем «что если»:
 * события материалов из `exclude_history` убираются, события `add_history` добавляются после последнего
 * события истории, их `seq` задаёт порядок между собой.
 */
export interface FeedRequest {
  /**
   * @maxItems 200
   */
  add_history?: HistoryEventIn[];
  /**
   * @maxItems 200
   */
  exclude_history?: string[];
  experience?: ('none' | 'some' | 'experienced') | null;
  format_pref?: ('quick' | 'template' | 'course') | null;
  history?: HistoryEventIn[] | null;
  industry?:
    | (
        | 'horeca'
        | 'retail'
        | 'ecom'
        | 'services'
        | 'construction'
        | 'logistics'
        | 'b2b'
        | 'manufacturing'
        | 'wholesale'
        | 'b2g'
      )
    | null;
  limit?: number;
  price_weight?: number | null;
  stage?: ('idea' | 'start' | 'growth') | null;
  task?: string;
  user_id?: string | null;
}
export interface HistoryEventIn {
  event: 'view' | 'start' | 'complete' | 'purchase';
  material_id: string;
  seq: number;
}
export interface FeedResponse {
  catalog: CatalogInfo;
  facts: FeedFact[];
  history: FeedHistoryOut[];
  interests: FeedShare[];
  items: FeedItemOut[];
  message: string;
  request_id: string;
  sources: FeedSourceShare[];
  status: 'history' | 'cold';
  total_candidates: number;
  user: UserOut | null;
}
export interface FeedShare {
  label: string;
  share: number;
}
export interface FeedSourceShare {
  label: string;
  share: number;
  source: 'progress' | 'history' | 'content' | 'links' | 'task' | 'profile' | 'access' | 'popularity' | 'seen';
}
/**
 * Клиент из подключённого журнала: код, подпись, сегмент и размер истории.
 */
export interface UserOut {
  id: string;
  label: string;
  materials: number;
  paid: boolean;
  segment: string | null;
}
export interface HealthCatalog {
  coverage: {
    [k: string]: unknown;
  };
  disabled_features: string[];
  size: number;
  source: string;
  version: string;
}
export interface HealthResponse {
  catalog: HealthCatalog;
  status: 'ok';
}
export interface HistoryEventOut {
  event: 'view' | 'start' | 'complete' | 'purchase';
  material_id: string;
  seq: number;
}
export interface MetaResponse {
  demo_mode: boolean;
  experience: Option[];
  formats: Option[];
  industries: Option[];
  max_task_length: number;
  stages: Option[];
  topics: Option[];
}
export interface ModelCardGroup {
  code: string;
  label: string;
  rows: ModelCardRow[];
  users: number;
}
/**
 * Метод на журнале записей: доля пользователей, у которых скрытый курс стоит первым и в первых пяти.
 */
export interface ModelCardRow {
  hit1: number;
  hit5: number;
  label: string;
  method: string;
  ndcg5: number;
}
/**
 * Паспорт модели ленты: тип данных проверки, качество по группам, веса источников и свойства ленты.
 */
export interface ModelCardResponse {
  data: string;
  feed: ModelCardValue[];
  groups: ModelCardGroup[];
  weights: ModelCardValue[];
}
export interface ModelCardValue {
  label: string;
  share: boolean;
  value: number;
}
/**
 * Ответ /api/live и /api/ready: только статус, без сведений о каталоге.
 */
export interface ProbeResponse {
  status: 'ok';
}
export interface ProfileOut {
  description: string;
  experience: ('none' | 'some' | 'experienced') | null;
  format_pref: ('quick' | 'template' | 'course') | null;
  history: HistoryEventOut[];
  id: string;
  industry:
    | (
        | 'horeca'
        | 'retail'
        | 'ecom'
        | 'services'
        | 'construction'
        | 'logistics'
        | 'b2b'
        | 'manufacturing'
        | 'wholesale'
        | 'b2g'
      )
    | null;
  label: string;
  stage: ('idea' | 'start' | 'growth') | null;
  task: string;
}
export interface ProfilesResponse {
  profiles: ProfileOut[];
}
export interface RecommendRequest {
  experience?: ('none' | 'some' | 'experienced') | null;
  format_pref?: ('quick' | 'template' | 'course') | null;
  history?: HistoryEventIn[] | null;
  industry?:
    | (
        | 'horeca'
        | 'retail'
        | 'ecom'
        | 'services'
        | 'construction'
        | 'logistics'
        | 'b2b'
        | 'manufacturing'
        | 'wholesale'
        | 'b2g'
      )
    | null;
  limit?: number;
  method?: 'personal' | 'baseline';
  profile_id?: string | null;
  stage?: ('idea' | 'start' | 'growth') | null;
  task?: string;
  topic?:
    | (
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
        | 'marketplaces'
      )
    | null;
}
/**
 * Клиенты, код которых начинается с запроса: первые `limit` из `matched`; `total` — всего в журнале.
 */
export interface UsersResponse {
  matched: number;
  source: string;
  total: number;
  users: UserOut[];
}
