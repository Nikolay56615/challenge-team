import { useState, type Ref } from 'react';
import type { ExperienceCode, Item } from '../api/types';
import { formatDuration, formatLessonCount, joinReasons, toSentence, typo } from '../format';
import { Badge, Button, ButtonLink, Card, Disclosure, KeyValue, MatchChips, RankMarker, safeHttpUrl } from '../kit';
import { matchLabels } from '../match';

export interface MaterialCardProps {
  item: Item;
  linkNoteInList?: boolean;
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

export const MISSING_LINKS_NOTE = typo('У\u00a0материалов в\u00a0этой подборке нет ссылок на платформу.');

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

/**
 * Анатомия карточки: docs/ui-kit.md, раздел 4. Порядок по F-паттерну: название, ключевые факты
 * (бейджи и краткая польза платного), причина с пометками «Совпало», следующий шаг, действия.
 * Тексты ответа выводятся через типограф: неразрывные пробелы и короткое тире (кандидат D09).
 */
export function MaterialCard({
  item,
  compact = false,
  showTopics = true,
  linkNoteInList = false,
  onComplete,
  cardRef,
  experience = null,
}: MaterialCardProps) {
  const [copyFeedback, setCopyFeedback] = useState('');
  const free = isFree(item);
  const duration = formatDuration(item.duration_minutes);
  const lessons = item.format === 'course' ? item.lesson_count : null;
  const completed = item.flags.some((flag) => flag.code === 'completed');
  const href = materialHref(item);
  const reasons = typo(joinReasons(item.reasons));
  const nextStep = typo(toSentence(item.next_step));
  const course = item.format === 'course' ? item.course_details : null;
  const description = course?.description ?? (!compact && !free ? item.short_benefit : null);
  const sections = [
    { label: 'Кому подойдёт', points: course?.audiences },
    { label: 'Результаты обучения', points: course?.outcomes },
  ].filter((section) => section.points?.length);

  const copyTitle = async () => {
    try {
      await navigator.clipboard.writeText(item.title);
      setCopyFeedback('Название скопировано');
    } catch {
      setCopyFeedback(typo('Выделите название материала и\u00a0скопируйте его вручную.'));
    }
  };


  const matched = matchLabels(item.contributions, { level: item.level, experience });

  const markButton = completed || !onComplete ? null : (
    <Button variant="link" size="sm" onClick={() => { onComplete(item); }}>
      Отметить изученным
    </Button>
  );

  return (
    <Card label={`Позиция ${String(item.rank)}`} ref={cardRef} tabIndex={cardRef ? -1 : undefined}>
      <div className="card__head">
        <RankMarker rank={item.rank} />
        <h3 className="h3 card__title">{typo(item.title)}</h3>
      </div>

      <div className="badges">
        {showTopics &&
          item.topic_labels.slice(0, 2).map((label, index) => (
            <Badge key={`topic-${String(index)}`} tone="topic">
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

      {description ? <p className="card__benefit">{typo(toSentence(description))}</p> : null}
      {sections.length ? (
        <Disclosure summary={typo('Подробнее о\u00a0курсе')} className="course-details">
          {sections.map(({ label, points }) => (
            <div key={label}>
              <p className="kv__label">{label}</p>
              <ul>{points?.map((point) => <li key={point}>{point}</li>)}</ul>
            </div>
          ))}
        </Disclosure>
      ) : null}
      {reasons ? <KeyValue label={compact ? 'Почему' : 'Почему подходит'}>{reasons}</KeyValue> : null}
      <MatchChips items={matched} />
      {!compact && href && nextStep ? <KeyValue label="Следующий шаг">{nextStep}</KeyValue> : null}

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
            <Button variant="secondary" size="sm" onClick={() => { void copyTitle(); }}>Скопировать название</Button>
            {markButton}
            {!linkNoteInList ? <span className="note">Ссылка на платформу не передана</span> : null}
          </>
        )}
      </div>
      {!href ? <p role="status" className={copyFeedback ? 'note' : 'visually-hidden'}>{copyFeedback}</p> : null}
    </Card>
  );
}
