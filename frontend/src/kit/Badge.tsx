import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from './cx';

export type BadgeTone = 'neutral' | 'free' | 'paid' | 'flag' | 'topic';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  children: ReactNode;
}

/** span.badge. Текст обязателен, цвет только дублирует смысл. */
export function Badge({ tone = 'neutral', className, children, ...rest }: BadgeProps) {
  return (
    <span {...rest} className={cx('badge', tone !== 'neutral' && `badge--${tone}`, className)}>
      {children}
    </span>
  );
}
