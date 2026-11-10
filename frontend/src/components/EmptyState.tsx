import { useId, type Ref } from 'react';
import type { Item, RecommendResponse, TopicCode } from '../api/types';
import { Button, ChipGroup, Panel } from '../kit';
import { MAX_LIMIT } from '../state/useRecommend';
import { MaterialCard } from './MaterialCard';

/** Сколько карточек стартовой подборки видно до «Показать все N» */
export const STARTER_VISIBLE = 3;

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
  expanded,
  onExpand,
  headingRef,
  focusIndex = null,
  cardRef,
}: EmptyStateProps) {
  const uid = useId();
  const headingId = `${uid}-title`;
  const starterId = `${uid}-starter`;

  const isEmpty = response.status === 'empty';
  const clarification = isEmpty ? null : response.clarification;
  const heading = response.status === 'cold' && clarification?.question ? clarification.question : response.message;
  const options = clarification?.options ?? [];
  const starter = isEmpty ? [] : response.items;
  const visible = expanded ? starter : starter.slice(0, STARTER_VISIBLE);
  const total = isEmpty ? 0 : starterTotal(response);

  return (
    <div className="results">
      <Panel labelledBy={headingId}>
        <h2 id={headingId} ref={headingRef} className="h2" tabIndex={-1}>
          {heading}
        </h2>
        {clarification?.text ? <p className="lead">{clarification.text}</p> : null}
        {options.length > 0 ? (
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
          {visible.map((item, index) => (
            <MaterialCard
              key={item.material_id}
              item={item}
              compact
              showTopics
              onComplete={onComplete}
              cardRef={index === focusIndex ? cardRef : undefined}
            />
          ))}
          {total > visible.length ? (
            <Button variant="secondary" onClick={onExpand}>
              Показать все {total}
            </Button>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
