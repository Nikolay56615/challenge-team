// Совместимость ручных типов src/api/types.ts со схемой OpenAPI бэкенда.
// Типы схемы создаёт npm run gen:api в src/api/schema.gen.ts. Файл проверяет tsc при npm run typecheck
// и npm run build; приложение его не импортирует, в бандл он не попадает. Расхождение — ошибка компиляции
// с именем проверки ниже.
import type * as Gen from './schema.gen';
import type * as Api from './types';

/** A присваивается B */
type Assignable<A, B> = [A] extends [B] ? true : false;
/** Одинаковые множества значений */
type Equal<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
type Assert<T extends true> = T;

/**
 * Коды из списков фронтенда расширены до string. Так сравнивается структура: имена полей, обязательность,
 * null и вложенность. Сами списки кодов сверяются отдельно в CodeLists.
 */
type Widen<T> = T extends string
  ? string
  : T extends readonly (infer U)[]
    ? Widen<U>[]
    : T extends object
      ? { [K in keyof T]: Widen<T[K]> }
      : T;

/** Ключи, которых нет в схеме: сервер отвечает 422 на лишнее поле запроса (extra="forbid") */
type ExtraKeys<A, B> = Exclude<keyof A, keyof B>;

/**
 * Запрос: то, что отправляет фронтенд, принимает API. В схеме поля со значениями по умолчанию необязательны,
 * фронтенд отправляет все.
 */
export type RequestChecks = [
  Assert<Assignable<Api.RecommendRequest, Gen.RecommendRequest>>,
  Assert<Equal<ExtraKeys<Api.RecommendRequest, Gen.RecommendRequest>, never>>,
  Assert<Assignable<Api.HistoryEvent, Gen.HistoryEventIn>>,
  Assert<Assignable<Api.FeedRequest, Gen.FeedRequest>>,
  Assert<Equal<ExtraKeys<Api.FeedRequest, Gen.FeedRequest>, never>>,
];

/** Ответы: то, что возвращает API, подходит под типы фронтенда */
export type ResponseChecks = [
  Assert<Assignable<Gen.RecommendResponse, Widen<Api.RecommendResponse>>>,
  Assert<Assignable<Gen.ItemOut, Widen<Api.Item>>>,
  Assert<Assignable<Gen.CompareResponse, Widen<Api.CompareResponse>>>,
  Assert<Assignable<Gen.MetaResponse, Widen<Api.MetaResponse>>>,
  Assert<Assignable<Gen.ProfilesResponse, Widen<Api.ProfilesResponse>>>,
  Assert<Assignable<Gen.Clarification, Widen<Api.Clarification>>>,
  Assert<Assignable<Gen.Route, Widen<Api.Route>>>,
  Assert<Assignable<Gen.FeedResponse, Widen<Api.FeedResponse>>>,
  Assert<Assignable<Gen.FeedItemOut, Widen<Api.FeedItem>>>,
  Assert<Assignable<Gen.UsersResponse, Widen<Api.UsersResponse>>>,
  Assert<Assignable<Gen.ModelCardResponse, Widen<Api.ModelCard>>>,
];

/**
 * Конверт ошибки совпадает со схемой: code, message и details обязательны и там, и тут. Тело ответа клиент
 * проверяет при разборе (httpError в client.ts), а ApiError.details строит по типу ApiErrorBody и дальше читает
 * без проверки. Equal ловит разную обязательность и поле, обязательное только с одной стороны. Необязательное
 * поле только с одной стороны Equal пропускает, поэтому имена полей сверяются отдельно на каждом уровне.
 */
export type ErrorChecks = [
  Assert<Equal<Gen.ErrorResponse, Api.ApiErrorBody>>,
  Assert<Equal<keyof Gen.ErrorResponse, keyof Api.ApiErrorBody>>,
  Assert<Equal<keyof Gen.ErrorBody, keyof Api.ApiErrorBody['error']>>,
  Assert<Equal<keyof Gen.ErrorDetail, keyof Api.ApiErrorBody['error']['details'][number]>>,
];

/**
 * Списки кодов совпадают в обе стороны: новый статус или формат доступа в API без правки фронтенда
 * не соберётся, лишний код во фронтенде — тоже.
 */
export type CodeLists = [
  Assert<Equal<Gen.RecommendResponse['status'], Api.StatusCode>>,
  Assert<Equal<Gen.RecommendResponse['method'], Api.MethodCode>>,
  Assert<Equal<NonNullable<Gen.RecommendRequest['method']>, Api.MethodCode>>,
  Assert<Equal<Gen.ItemOut['access'], Api.AccessCode>>,
  Assert<Equal<Gen.FlagOut['code'], Api.FlagCode>>,
  Assert<Equal<Gen.HistoryEventIn['event'], Api.EventCode>>,
  Assert<Equal<NonNullable<Gen.RecommendRequest['stage']>, Api.StageCode>>,
  Assert<Equal<NonNullable<Gen.RecommendRequest['experience']>, Api.ExperienceCode>>,
  Assert<Equal<NonNullable<Gen.RecommendRequest['format_pref']>, Api.FormatPrefCode>>,
  Assert<Equal<NonNullable<Gen.RecommendRequest['industry']>, Api.IndustryCode>>,
  Assert<Equal<NonNullable<Gen.RecommendRequest['topic']>, Api.TopicCode>>,
  Assert<Equal<NonNullable<Gen.ProfileOut['stage']>, Api.StageCode>>,
  Assert<Equal<Gen.FeedPart['source'], Api.FeedSourceCode>>,
  Assert<Equal<Gen.FeedSourceShare['source'], Api.FeedSourceCode>>,
  Assert<Equal<Gen.FeedResponse['status'], Api.FeedStatus>>,
  Assert<Equal<Gen.FeedHistoryOut['event'], Api.EventCode>>,
];

/**
 * Сужения фронтенда: схема отдаёт строку, интерфейс ждёт код из своего списка. Проверки фиксируют, что
 * схема здесь действительно шире: если бэкенд объявит перечисление, проверка упадёт, и сужение можно
 * заменить сверкой списков в CodeLists.
 * - detected_topics и значения вариантов уточнения — коды тем: их выбор уходит в поле topic запроса;
 * - значения вариантов /api/meta — коды стадий, опыта, форматов и сфер для полей запроса.
 */
export type KnownNarrowing = [
  Assert<Equal<Gen.RecommendResponse['detected_topics'][number], string>>,
  Assert<Equal<Gen.Option['value'], string>>,
];
