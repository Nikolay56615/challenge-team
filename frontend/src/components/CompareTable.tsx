import type { FeedItem } from '../api/types';
import { FAMILY_OF, compareRows, formatDelta, formatScore } from '../feed';
import { typo } from '../format';
import { cx } from '../kit';

export interface CompareTableProps {
  caption: string;
  a: FeedItem;
  b: FeedItem;
}

/** Две карточки рядом: вклады источников у каждой и разница. Вывод читатель делает сам по числам. */
export function CompareTable({ caption, a, b }: CompareTableProps) {
  return (
    <table className="compare-table">
      <caption>{typo(caption)}</caption>
      <thead>
        <tr>
          <th scope="col">Источник</th>
          <th scope="col">Место {String(a.rank)}</th>
          <th scope="col">Место {String(b.rank)}</th>
          <th scope="col">Разница</th>
        </tr>
      </thead>
      <tbody>
        {compareRows(a, b).map((row) => {
          const family = FAMILY_OF[row.source];
          return (
            <tr key={row.source}>
              <th scope="row">
                <span className={cx('swatch', family ? `swatch--${family}` : 'swatch--none')} aria-hidden="true" />
                {typo(row.label)}
              </th>
              <td>{formatScore(row.a)}</td>
              <td>{formatScore(row.b)}</td>
              <td>{row.delta === 0 ? '0' : formatDelta(row.delta)}</td>
            </tr>
          );
        })}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">Оценка</th>
          <td>{formatScore(a.score)}</td>
          <td>{formatScore(b.score)}</td>
          <td>{a.score === b.score ? '0' : formatDelta(Math.round((a.score - b.score) * 100) / 100)}</td>
        </tr>
      </tfoot>
    </table>
  );
}
