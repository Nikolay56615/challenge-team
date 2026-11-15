import type { FeedResponse } from '../api/types';
import { FAMILY_LABEL, formatScore, formatShare, shareSegments } from '../feed';
import { typo } from '../format';

const ROWS = 10;

export interface ClientCompareProps {
  /** Лента клиента, выбранного на экране */
  own: FeedResponse;
  /** Лента клиента, с которым её сравнивают */
  other: FeedResponse;
}

/** Полоса долей источников в оценках показанных карточек одного клиента */
function ShareBar({ feed, name }: { feed: FeedResponse; name: string }) {
  const segments = shareSegments(feed.sources);
  const label = segments.map((segment) => `${FAMILY_LABEL[segment.family]} ${formatShare(segment.value)}`).join(', ');
  return (
    <div className="client-compare__bar">
      <span className="client-compare__name">{name}</span>
      <span className="score-bar" role="img" aria-label={typo(`Доли источников у\u00A0клиента ${name}: ${label}`)}>
        {segments.map((segment) => (
          <span
            key={segment.family}
            className={`score-bar__seg score-bar__seg--${segment.family}`}
            style={{ width: `${String(segment.value * 100)}%` }}
            title={`${FAMILY_LABEL[segment.family]}: ${formatShare(segment.value)}`}
          />
        ))}
      </span>
    </div>
  );
}

/**
 * Два клиента рядом: число общих карточек, доли источников у каждого и первые десять карточек обеих лент
 * по местам. Вывода текстом нет: видно, какие карточки совпали и от каких источников пришли оценки.
 */
export function ClientCompare({ own, other }: ClientCompareProps) {
  const a = own.user?.id ?? 'Первый';
  const b = other.user?.id ?? 'Второй';
  const depth = Math.min(own.items.length, other.items.length);
  const rows = Array.from({ length: Math.min(ROWS, depth) }, (_, index) => index);
  // Пометка «есть у обоих» относится к строкам таблицы: обе карточки видны на экране
  const inOther = new Set(other.items.slice(0, rows.length).map((item) => item.material_id));
  const inOwn = new Set(own.items.slice(0, rows.length).map((item) => item.material_id));
  return (
    <section className="client-compare" aria-label={typo(`Клиенты ${a} и\u00A0${b} рядом`)}>
      <h2 className="client-compare__title">{typo(`Клиенты ${a} и\u00A0${b} рядом`)}</h2>
      <ShareBar feed={own} name={a} />
      <ShareBar feed={other} name={b} />
      <table className="compare-table client-compare__table">
        <caption className="visually-hidden">{typo(`Первые ${String(rows.length)} карточек каждой ленты`)}</caption>
        <thead>
          <tr>
            <th scope="col">Место</th>
            <th scope="col">{a}</th>
            <th scope="col">{b}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((index) => {
            const left = own.items[index];
            const right = other.items[index];
            return (
              <tr key={index}>
                <th scope="row">{String(index + 1)}</th>
                {[left, right].map((item, side) =>
                  item ? (
                    <td key={side === 0 ? 'own' : 'other'}>
                      {typo(item.title)} <span className="client-compare__score">{formatScore(item.score)}</span>
                      {(side === 0 ? inOther : inOwn).has(item.material_id) ? (
                        <span className="client-compare__shared"> есть у&nbsp;обоих</span>
                      ) : null}
                    </td>
                  ) : (
                    <td key={side === 0 ? 'own' : 'other'} />
                  ),
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
