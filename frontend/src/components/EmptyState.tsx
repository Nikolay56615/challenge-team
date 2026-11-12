import { useId, useState, type Ref } from 'react';
import type { Item, RecommendResponse, TopicCode } from '../api/types';
import { formatShownMaterials } from '../format';
import { Button, ChipGroup, Panel } from '../kit';
import { MAX_LIMIT } from '../state/useRecommend';
import { hasNoMaterialLinks, MaterialCard, MISSING_LINKS_NOTE } from './MaterialCard';
import { TopicPicker } from './TopicPicker';

/** Сколько карточек стартовой подборки видно до «Показать все N» */
export const STARTER_VISIBLE = 3;
const MAX_TOPIC_CHIPS = 7;

/** N в «Показать все N»: вся стартовая подборка по total_candidates, не больше предела API */
export function starterTotal(response: RecommendResponse): number {
  return Math.min(Math.max(response.total_candidates, response.items.length), MAX_LIMIT);
}

export interface EmptyStateProps {
  /** status: none, cold или empty */
  response: RecommendResponse;
  topic: TopicCode | null;
  onChooseTopic?(topic: TopicCode): void;
  onComplete?(item: Item): void;
  /** Идёт повторный запрос: прежние данные ещё на экране */
  busy?: boolean;
  /** Подборка раскрыта. Флаг хранит экран: он переживает повтор запроса */
  expanded: boolean;
  /** «Показать все N»: экран раскрывает подборку и при нехватке карточек запрашивает до 10 */
  onExpand?(): void;
  /** Заголовок принимает фокус, когда нажатый элемент исчез вместе с прежним ответом */
  headingRef?: Ref<HTMLHeadingElement>;
  /** Карточка с этим индексом получает cardRef: на неё переходит фокус после раскрытия */
  focusIndex?: number | null;
  cardRef?: Ref<HTMLElement>;
}

/**
 * none — сообщение о пробеле; cold — вопрос «С чего хотите начать?» без сообщения о пробеле;
 * empty — только сообщение. Видны три карточки стартовой подборки, остальные по кнопке.
 */
export function EmptyState({
  response,
  topic,
  onChooseTopic,
  onComplete,
  busy = false,
  expanded,
  onExpand,
  headingRef,
  focusIndex = null,
  cardRef,
}: EmptyStateProps) {
  const uid = useId();
  const headingId = `${uid}-title`;
  const starterId = `${uid}-starter`;
  const [selectedTopic, setSelectedTopic] = useState<TopicCode | null>(null);

  const isEmpty = response.status === 'empty';
  const clarification = isEmpty ? null : response.clarification;
  const heading = response.status === 'cold' && clarification?.question ? clarification.question : response.message;
  const options = clarification?.options ?? [];
  const starter = isEmpty ? [] : response.items;
  const visible = expanded ? starter : starter.slice(0, STARTER_VISIBLE);
  const total = isEmpty ? 0 : starterTotal(response);
  const linksMissing = hasNoMaterialLinks(visible);

  return (
    <div className="results">
      <Panel labelledBy={headingId}>
        <h2 id={headingId} ref={headingRef} className="h2" tabIndex={-1}>
          {heading}
        </h2>
        {clarification?.text ? <p className="lead">{clarification.text}</p> : null}
        {options.length > MAX_TOPIC_CHIPS ? (
          <TopicPicker
            label="Тема"
            options={options}
            value={selectedTopic}
            onChange={setSelectedTopic}
            onShow={(value) => onChooseTopic?.(value)}
          />
        ) : options.length > 0 ? (
          <ChipGroup
            legend="Тема"
            legendHidden
            name="empty-topic"
            options={options}
            value={topic}
            onChange={(value) => {
              if (value) onChooseTopic?.(value);
            }}
            allowDeselect={false}
            activation="manual"
          />
        ) : null}
      </Panel>

      {starter.length > 0 ? (
        <section className="starter" aria-labelledby={starterId}>
          <h2 id={starterId} className="h2">
            Стартовая подборка
          </h2>
          <p className="note">{formatShownMaterials(visible.length, response.total_candidates)}</p>
          {linksMissing ? <p className="note">{MISSING_LINKS_NOTE}</p> : null}
          {visible.map((item, index) => (
            <MaterialCard
              key={item.material_id}
              item={item}
              compact
              linkNoteInList={linksMissing}
              busy={busy}
              onComplete={onComplete}
              cardRef={index === focusIndex ? cardRef : undefined}
            />
          ))}
          {total > visible.length ? (
            <Button
              variant="secondary"
              aria-disabled={busy || undefined}
              onClick={() => {
                if (!busy) onExpand?.();
              }}
            >
              Показать все {total}
            </Button>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
