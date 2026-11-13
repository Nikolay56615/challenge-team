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
  CourseDetailsOut: CourseDetailsOut;
  ErrorBody: ErrorBody;
  ErrorDetail: ErrorDetail;
  ErrorResponse: ErrorResponse;
  FilterOptionsOut: FilterOptionsOut;
  FiltersIn: FiltersIn;
  FlagOut: FlagOut;
  HealthCatalog: HealthCatalog;
  HealthResponse: HealthResponse;
  HistoryEventIn: HistoryEventIn;
  HistoryEventOut: HistoryEventOut;
  ItemOut: ItemOut;
  MetaCatalog: MetaCatalog;
  MetaResponse: MetaResponse;
  Option: Option;
  ProbeResponse: ProbeResponse;
  ProfileOut: ProfileOut;
  ProfilesResponse: ProfilesResponse;
  RecommendRequest: RecommendRequest;
  RecommendResponse: RecommendResponse;
  Route: Route;
  RouteStep: RouteStep;
  SignalOut: SignalOut;
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
  filter_options?: FilterOptionsOut | null;
  items: ItemOut[];
  message: string;
  method: 'personal' | 'baseline';
  request_id: string;
  route: Route | null;
  status: 'strong' | 'weak' | 'none' | 'cold' | 'empty';
  total_candidates: number;
}
export interface FilterOptionsOut {
  access: Option[];
  formats: Option[];
}
export interface ItemOut {
  access: 'open' | 'subscription' | 'paid';
  access_label: string;
  contributions: {
    [k: string]: number;
  };
  course_details?: CourseDetailsOut | null;
  duration_minutes: number | null;
  flags: FlagOut[];
  format: string;
  format_label: string;
  has_certificate?: boolean | null;
  industries: string[];
  is_paid: boolean;
  lesson_count?: number | null;
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
export interface CourseDetailsOut {
  audiences: string[];
  description: string | null;
  outcomes: string[];
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
export interface FiltersIn {
  access?: ('open' | 'subscription' | 'paid') | null;
  format?: ('checklist' | 'article' | 'template' | 'document' | 'video' | 'course' | 'webinar' | 'podcast') | null;
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
export interface HistoryEventIn {
  event: 'view' | 'start' | 'complete' | 'purchase';
  material_id: string;
  seq: number;
}
export interface HistoryEventOut {
  event: 'view' | 'start' | 'complete' | 'purchase';
  material_id: string;
  seq: number;
}
export interface MetaCatalog {
  available: number;
  source: string;
}
export interface MetaResponse {
  catalog: MetaCatalog;
  demo_mode: boolean;
  experience: Option[];
  formats: Option[];
  industries: Option[];
  max_task_length: number;
  stages: Option[];
  topics: Option[];
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
  filters?: FiltersIn | null;
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
