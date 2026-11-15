import type { Ref } from 'react';
import type { ExperienceCode, Item } from '../api/types';
import { formatDuration, joinReasons, toSentence, typo } from '../format';
import { Badge, Button, ButtonLink, Card, KeyValue, MatchChips, RankMarker, safeHttpUrl } from '../kit';
import { matchLabels } from '../match';

export interface MaterialCardProps {
  item: Item;
  /** Компактная карточка: позиция, бейджи, «Почему», «Совпало», действия */
  compact?: boolean;
  /** Бейдж темы — только в смешанной (weak) и стартовой (none, cold) выдаче */
  showTopics?: boolean;
  /** Списки передают обработчик и ссылку как есть, поэтому undefined разрешён явно (exactOptionalPropertyTypes) */
  onComplete?: ((item: Item) => void) | undefined;
  /** Для переноса фокуса на карточку: после ответа, после раскрытия списка */
  cardRef?: Ref<HTMLElement> | undefined;
  /** Опыт из запроса этой выдачи: пометка «уровень» только при точном совпадении уровня (src/match.ts) */
  experience?: ExperienceCode | null;
}

export function isFree(item: Item): boolean {
  return item.access === 'open' && !item.is_paid;
}

function linkLabel(item: Item): string {
  if (isFree(item)) return 'Открыть материал';
  return item.format === 'course' ? 'Открыть страницу курса' : 'Открыть страницу материала';
}

const COURSE_COVERS: Readonly<Partial<Record<string, string>>> = {
  taxes_law: 'finance',
  finance: 'finance',
  marketing: 'marketing',
  sales: 'marketing',
  start: 'business',
  team: 'business',
  strategy: 'business',
  operations: 'business',
};

/**
 * Анатомия карточки: docs/ui-kit.md, раздел 4. Порядок по F-паттерну: название, ключевые факты
 * (бейджи и краткая польза платного), причина с пометками «Совпало», следующий шаг, действия.
 * Тексты ответа выводятся через типограф: неразрывные пробелы и короткое тире.
 */
export function MaterialCard({
  item,
  compact = false,
  showTopics = false,
  onComplete,
  cardRef,
  experience = null,
}: MaterialCardProps) {
  const free = isFree(item);
  const duration = formatDuration(item.duration_minutes);
  const completed = item.flags.some((flag) => flag.code === 'completed');
  const href = item.link_allowed ? safeHttpUrl(item.url) : null;
  const reasons = typo(joinReasons(item.reasons));
  const nextStep = typo(toSentence(item.next_step));
  const benefit = !compact && (item.format === 'course' || !free) && item.short_benefit
    ? typo(toSentence(item.short_benefit))
    : '';
  const cover = !compact && item.format === 'course' ? (COURSE_COVERS[item.topics[0] ?? ''] ?? 'business') : null;
  const matched = matchLabels(item.contributions, { level: item.level, experience });

  const markButton = completed ? null : (
    <Button variant="link" size="sm" onClick={() => onComplete?.(item)}>
      Отметить изученным
    </Button>
  );

  return (
    <Card label={`Позиция ${String(item.rank)}`} ref={cardRef} tabIndex={cardRef ? -1 : undefined}>
      <div className="card__head">
        <RankMarker rank={item.rank} />
        <h3 className="h3 card__title">{typo(item.title)}</h3>
        {cover ? (
          <img className="card__cover" src={`/course-topics/${cover}.jpg`} alt="" width="96" height="64" loading="lazy" />
        ) : null}
      </div>

      {benefit ? <p className="card__benefit">{benefit}</p> : null}

      <div className="badges">
        {showTopics &&
          item.topic_labels.map((label, index) => (
            <Badge key={`topic-${String(index)}`} tone="topic">
              {label}
            </Badge>
          ))}
        <Badge>{item.format_label}</Badge>
        {duration ? <Badge>{duration}</Badge> : null}
        <Badge tone={free ? 'free' : 'paid'}>{item.access_label}</Badge>
        {item.level_label ? <Badge>{item.level_label}</Badge> : null}
        {item.flags.map((flag) => (
          <Badge key={`flag-${flag.code}`} tone="flag">
            {flag.label}
          </Badge>
        ))}
      </div>

      {reasons ? <KeyValue label={compact ? 'Почему' : 'Почему подходит'}>{reasons}</KeyValue> : null}
      <MatchChips items={matched} />
      {!compact && nextStep ? <KeyValue label="Следующий шаг">{nextStep}</KeyValue> : null}

      <div className="card__actions">
        {href ? (
          <>
            <ButtonLink href={href} external variant={free ? 'secondary' : 'outline'} size="sm">
              {linkLabel(item)}
            </ButtonLink>
            {markButton}
          </>
        ) : (
          markButton
        )}
      </div>
    </Card>
  );
}
