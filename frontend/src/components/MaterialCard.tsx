import type { Ref } from 'react';
import type { Item } from '../api/types';
import { formatDuration, joinReasons, toSentence } from '../format';
import { Badge, Button, ButtonLink, Card, KeyValue, RankMarker, safeHttpUrl } from '../kit';

export interface MaterialCardProps {
  item: Item;
  /** Компактная карточка: позиция, бейджи, «Почему», действия */
  compact?: boolean;
  /** Бейдж темы — только в смешанной (weak) и стартовой (none, cold) выдаче */
  showTopics?: boolean;
  onComplete?(item: Item): void;
  /** Для переноса фокуса на карточку после раскрытия списка */
  cardRef?: Ref<HTMLElement>;
}

export function isFree(item: Item): boolean {
  return item.access === 'open' && !item.is_paid;
}

function linkLabel(item: Item): string {
  if (isFree(item)) return 'Открыть материал';
  return item.format === 'course' ? 'Открыть страницу курса' : 'Открыть страницу материала';
}

/** Анатомия карточки: design/ui-kit.md, раздел 4 */
export function MaterialCard({ item, compact = false, showTopics = false, onComplete, cardRef }: MaterialCardProps) {
  const free = isFree(item);
  const duration = formatDuration(item.duration_minutes);
  const completed = item.flags.some((flag) => flag.code === 'completed');
  const href = item.link_allowed ? safeHttpUrl(item.url) : null;
  const reasons = joinReasons(item.reasons);
  const nextStep = toSentence(item.next_step);
  const benefit = !free && item.short_benefit ? toSentence(item.short_benefit) : '';

  const markButton = completed ? null : (
    <Button variant="link" size="sm" onClick={() => onComplete?.(item)}>
      Отметить изученным
    </Button>
  );

  return (
    <Card label={`Позиция ${item.rank}`} ref={cardRef} tabIndex={cardRef ? -1 : undefined}>
      <div className="card__head">
        <RankMarker rank={item.rank} />
        <h3 className="h3 card__title">{item.title}</h3>
      </div>

      <div className="badges">
        {showTopics &&
          item.topic_labels.map((label, index) => (
            <Badge key={`topic-${index}`} tone="topic">
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

      {!compact && benefit ? <p className="card__benefit">{benefit}</p> : null}
      {reasons ? <KeyValue label={compact ? 'Почему' : 'Почему подходит'}>{reasons}</KeyValue> : null}
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
          <>
            {markButton}
            <span className="note">Ссылка на платформу не передана</span>
          </>
        )}
      </div>
    </Card>
  );
}
