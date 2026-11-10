import type { HTMLAttributes } from 'react';
import { cx } from './cx';

/** Атрибуты применяются к каждому скелетону; id не принимается: элементов несколько */
export interface SkeletonProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'id'> {
  count?: number;
}

/** div.skeleton: статичный градиент; о загрузке сообщает StatusLine */
export function Skeleton({ count = 1, className, ...rest }: SkeletonProps) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} {...rest} className={cx('skeleton', className)} aria-hidden="true" />
      ))}
    </>
  );
}
