import { useState, type Ref } from 'react';
import type { Item } from '../api/types';
import { formatDuration, formatLessonCount, joinReasons, toSentence } from '../format';
import { Badge, Button, ButtonLink, Card, Disclosure, KeyValue, RankMarker, safeHttpUrl } from '../kit';

export interface MaterialCardProps {
  item: Item;
  /** Компактная карточка: краткая подпись к причинам */
  compact?: boolean;
  /** Пояснение об отсутствии ссылок уже показано над выдачей */
  linkNoteInList?: boolean;
  /** Идёт повторный запрос: прежние данные ещё на экране */
  busy?: boolean;
  onComplete?(item: Item): void;
  /** Для переноса фокуса на карточку после раскрытия списка */
  cardRef?: Ref<HTMLElement>;
}

export function isFree(item: Item): boolean {
  return item.access === 'open' && !item.is_paid;
}

export const MISSING_LINKS_NOTE = 'У материалов в этой подборке нет ссылок на платформу.';

function materialHref(item: Item): string | null {
  return item.link_allowed ? safeHttpUrl(item.url) : null;
}

export function hasNoMaterialLinks(items: readonly Item[]): boolean {
  return items.length > 0 && items.every((item) => !materialHref(item));
}

function linkLabel(item: Item): string {
  if (isFree(item)) return 'Открыть материал';
  return item.format === 'course' ? 'Открыть страницу курса' : 'Открыть страницу материала';
}

/** Анатомия карточки: design/ui-kit.md, раздел 4 */
export function MaterialCard({ item, compact = false, linkNoteInList = false, busy = false, onComplete, cardRef }: MaterialCardProps) {
  const [copyFeedback, setCopyFeedback] = useState('');
  const free = isFree(item);
  const duration = formatDuration(item.duration_minutes);
  const lessons = item.format === 'course' ? item.lesson_count : null;
  const completed = item.flags.some((flag) => flag.code === 'completed');
  const href = materialHref(item);
  const reasons = joinReasons(item.reasons);
  const nextStep = toSentence(item.next_step);
  const course = item.format === 'course' ? item.course_details : null;
  const description = course?.description || (!compact && !free ? item.short_benefit : null);
  const sections = [
    { label: 'Кому подойдёт', points: course?.audiences },
    { label: 'Результаты обучения', points: course?.outcomes },
  ].filter((section) => section.points?.length);

  const copyTitle = async () => {
    try {
      await navigator.clipboard.writeText(item.title);
      setCopyFeedback('Название скопировано');
    } catch {
      setCopyFeedback('Выделите название материала и скопируйте его вручную.');
    }
  };

  return (
    <Card label={`Позиция ${item.rank}`} ref={cardRef} tabIndex={cardRef ? -1 : undefined} aria-busy={busy || undefined}>
      <div className="card__head">
        <RankMarker rank={item.rank} />
        <h3 className="h3 card__title">{item.title}</h3>
      </div>

      <div className="badges">
        {item.topic_labels.slice(0, 2).map((label, index) => (
          <Badge key={`topic-${index}`} tone="topic">
            {label}
          </Badge>
        ))}
        <Badge>{item.format_label}</Badge>
        {duration ? <Badge>{duration}</Badge> : null}
        {lessons ? <Badge>{formatLessonCount(lessons)}</Badge> : null}
        {item.format === 'course' && item.has_certificate ? <Badge>Сертификат</Badge> : null}
        <Badge tone={free ? 'free' : 'paid'}>{item.access_label}</Badge>
        {item.level_label ? <Badge>{item.level_label}</Badge> : null}
        {item.flags.map((flag) => (
          <Badge key={`flag-${flag.code}`} tone="flag">
            {flag.label}
          </Badge>
        ))}
      </div>

      {description ? <p className="card__benefit">{toSentence(description)}</p> : null}
      {sections.length ? (
        <Disclosure summary="Подробнее о курсе" className="course-details">
          {sections.map(({ label, points }) => (
            <div key={label}>
              <p className="kv__label">{label}</p>
              <ul>{points?.map((point) => <li key={point}>{point}</li>)}</ul>
            </div>
          ))}
        </Disclosure>
      ) : null}
      {reasons ? <KeyValue label={compact ? 'Почему' : 'Почему подходит'}>{reasons}</KeyValue> : null}
      {href && nextStep ? <KeyValue label="Следующий шаг">{nextStep}</KeyValue> : null}

      <div className="card__actions">
        {href ? (
          <ButtonLink href={href} external variant={free ? 'secondary' : 'outline'} size="sm">
            {linkLabel(item)}
          </ButtonLink>
        ) : (
          <Button variant="secondary" size="sm" onClick={copyTitle}>
            Скопировать название
          </Button>
        )}
        {!completed && onComplete ? (
          <Button
            variant="link"
            size="sm"
            aria-disabled={busy || undefined}
            onClick={() => {
              if (!busy) onComplete(item);
            }}
          >
            Отметить изученным
          </Button>
        ) : null}
        {!href && !linkNoteInList && (
          <span className="note">Ссылка на платформу не передана</span>
        )}
      </div>
      {!href ? (
        <p role="status" className={copyFeedback ? 'note' : 'visually-hidden'}>{copyFeedback}</p>
      ) : null}
    </Card>
  );
}
