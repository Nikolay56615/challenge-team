import type { Ref } from 'react';
import type { Item, RecommendResponse } from '../api/types';
import { Button, Skeleton, StatusLine } from '../kit';
import { MAX_LIMIT } from '../state/useRecommend';
import { MaterialCard } from './MaterialCard';
import { RouteBlock } from './RouteBlock';

export const LOADING_STATUS = 'Подбираем материалы… Обычно это занимает меньше секунды.';

export interface ResultListProps {
  /** Текст строки состояния */
  status: string;
  /** Строка остаётся для вспомогательных технологий, но не видна */
  statusHidden?: boolean;
  statusRef?: Ref<HTMLParagraphElement>;
  /** Загрузка: три скелетона вместо карточек */
  loading?: boolean;
  response?: RecommendResponse | null;
  showTopics?: boolean;
  onComplete?(item: Item): void;
  onMore?(): void;
  /** Карточка с этим индексом получает cardRef: после «Показать ещё» фокус переходит на первую новую */
  focusIndex?: number | null;
  cardRef?: Ref<HTMLElement>;
  /** Заголовок выдачи: принимает фокус после ответа на отправку формы */
  headingRef?: Ref<HTMLHeadingElement>;
}

/**
 * Строка состояния, карточки, маршрут и «Показать ещё N».
 * Компонент смонтирован во всех состояниях экрана: строка состояния — одна живая область,
 * поэтому смена «Подбираем…» на итог объявляется без переноса фокуса.
 * Возвращает фрагмент: элементы встают в сетку layout__content, скрытые элементы места не занимают.
 */
export function ResultList({
  status,
  statusHidden = false,
  statusRef,
  loading = false,
  response,
  showTopics = false,
  onComplete,
  onMore,
  focusIndex = null,
  cardRef,
  headingRef,
}: ResultListProps) {
  const items = response?.items ?? [];
  const total = response?.total_candidates ?? 0;
  const more = Math.min(total, MAX_LIMIT) - items.length;
  const canShowMore = !loading && total > items.length && items.length < MAX_LIMIT && more > 0;
  const showItems = !loading && items.length > 0;

  return (
    <>
      <StatusLine ref={statusRef} tabIndex={-1} className={statusHidden ? 'visually-hidden' : undefined}>
        {status}
      </StatusLine>
      {loading ? <Skeleton count={3} /> : null}
      {/* Заголовок для навигации по заголовкам: карточки h3 не попадают под «Демо-режим» */}
      {showItems ? (
        <h2 ref={headingRef} className="visually-hidden" tabIndex={-1}>
          Подборка
        </h2>
      ) : null}
      {showItems &&
        items.map((item, index) => (
          <MaterialCard
            key={item.material_id}
            item={item}
            showTopics={showTopics}
            onComplete={onComplete}
            cardRef={index === focusIndex ? cardRef : undefined}
          />
        ))}
      {!loading && response?.route ? <RouteBlock route={response.route} /> : null}
      {canShowMore ? (
        <Button variant="secondary" onClick={onMore}>
          Показать ещё {more}
        </Button>
      ) : null}
    </>
  );
}
