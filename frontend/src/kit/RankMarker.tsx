import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface RankMarkerProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {
  rank: number;
}

/** span.rank; номер озвучивает aria-label карточки */
export function RankMarker({ rank, className, ...rest }: RankMarkerProps) {
  return (
    <span {...rest} className={cx('rank', className)} aria-hidden="true">
      {rank}
    </span>
  );
}
