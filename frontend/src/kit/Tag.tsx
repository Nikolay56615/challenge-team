import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from './cx';

export interface TagProps extends HTMLAttributes<HTMLSpanElement> {
  children: ReactNode;
}

/** span.tag: метка «Демо-данные» */
export function Tag({ className, children, ...rest }: TagProps) {
  return (
    <span {...rest} className={cx('tag', className)}>
      {children}
    </span>
  );
}
