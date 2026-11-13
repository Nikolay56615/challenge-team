import type { HTMLAttributes, ReactNode, Ref } from 'react';
import { cx } from './cx';

export interface CardProps extends HTMLAttributes<HTMLElement> {
  /** Доступное имя карточки: «Позиция N» */
  label: string;
  children: ReactNode;
  ref?: Ref<HTMLElement> | undefined;
}

/** article.card */
export function Card({ label, className, children, ...rest }: CardProps) {
  return (
    <article {...rest} className={cx('card', className)} aria-label={label}>
      {children}
    </article>
  );
}
