import type { ReactNode, Ref } from 'react';
import type { ExperienceCode, Item, RecommendResponse } from '../api/types';
import { formatShownMaterials } from '../format';
import { Button, Skeleton, Stale, StatusLine } from '../kit';
import { MAX_LIMIT } from '../state/useRecommend';
import { hasNoMaterialLinks, MaterialCard, MISSING_LINKS_NOTE } from './MaterialCard';
import { RouteBlock } from './RouteBlock';

export const LOADING_STATUS = 'Подбираем материалы… Обычно это занимает меньше секунды.';

export interface ResultListProps {
  /** Текст строки состояния */
  status: string;
  /** Строка остаётся для вспомогательных технологий, но не видна */
  statusHidden?: boolean;
  statusRef?: Ref<HTMLParagraphElement>;
  /** Загрузка дольше задержки скелетонов: три скелетона вместо выдачи (кандидат D10) */
  loading?: boolean;
  /**
   * Запрос идёт, задержка скелетонов ещё не истекла: прежняя выдача response остаётся на месте,
   * неактивная и приглушённая (Stale). Строка состояния уже говорит о загрузке.
   */
  stale?: boolean;
  response?: RecommendResponse | null;
  topicLabel?: string | undefined;
  headingRef?: Ref<HTMLHeadingElement>;
  filters?: ReactNode;
  onComplete?: (item: Item) => void;
  onMore?: () => void;
  /** Карточка с этим индексом получает cardRef: после «Показать ещё» фокус переходит на первую новую */
  focusIndex?: number | null;
  cardRef?: Ref<HTMLElement>;
  /** Первая карточка выдачи: на неё переходит фокус после ответа strong или weak (docs/ui-kit.md, 4.1) */
  firstCardRef?: Ref<HTMLElement>;
  /** Опыт из запроса этой выдачи: для пометки «уровень» (src/match.ts) */
  experience?: ExperienceCode | null;
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
  stale = false,
  response,
  topicLabel,
  headingRef,
  filters,
  onComplete,
  onMore,
  focusIndex = null,
  cardRef,
  firstCardRef,
  experience = null,
}: ResultListProps) {
  const items = response?.items ?? [];
  const total = response?.total_candidates ?? 0;
  const more = Math.min(total, MAX_LIMIT) - items.length;
  const canShowMore = !loading && total > items.length && items.length < MAX_LIMIT && more > 0;
  const showItems = !loading && items.length > 0;

  const filteredEmpty = !loading && Boolean(response?.filter_options) && total === 0;
  const linksMissing = hasNoMaterialLinks(items);

  return (
    <>
      <StatusLine ref={statusRef} tabIndex={-1} className={statusHidden ? 'visually-hidden' : undefined}>
        {status}
      </StatusLine>
      {loading ? <Skeleton count={3} /> : null}
      <Stale active={stale}>
        {/* Заголовок для навигации по заголовкам: карточки h3 не попадают под «Демо-режим» */}
      {showItems || filteredEmpty ? (
        <h2 ref={headingRef} className="h2" tabIndex={-1}>
          {topicLabel ? `Подборка по теме «${topicLabel}»`
            : filteredEmpty ? response?.message : formatShownMaterials(items.length, total)}
        </h2>
      ) : null}
      {showItems && topicLabel ? <p className="note">{formatShownMaterials(items.length, total)}</p> : null}
      {filteredEmpty && topicLabel ? <p>{response?.message}</p> : null}
      {filters}
      {showItems && linksMissing ? <p className="note">{MISSING_LINKS_NOTE}</p> : null}
        {showItems &&
          items.map((item, index) => (
            <MaterialCard
              key={item.material_id}
              item={item}
              linkNoteInList={linksMissing}
              onComplete={onComplete}
              cardRef={stale ? undefined : index === focusIndex ? cardRef : index === 0 ? firstCardRef : undefined}
              experience={experience}
            />
          ))}
        {!loading && response?.route ? <RouteBlock route={response.route} /> : null}
        {canShowMore ? (
          <Button variant="secondary" onClick={onMore}>
            Показать ещё {more}
          </Button>
        ) : null}
      {showItems && items.length >= MAX_LIMIT && total > items.length ? (
        <p className="note">Используйте фильтры, чтобы сузить список.</p>
      ) : null}
      </Stale>
    </>
  );
}
