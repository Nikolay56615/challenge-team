import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from './cx';

export interface BannerProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title' | 'children' | 'role'> {
  tone: 'info' | 'error';
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}

/** div.banner: информационный — role="status", ошибка — role="alert". Фокус не переносится. */
export function Banner({ tone, title, children, actions, className, ...rest }: BannerProps) {
  return (
    <div {...rest} className={cx('banner', `banner--${tone}`, className)} role={tone === 'error' ? 'alert' : 'status'}>
      <p className="banner__title">{title}</p>
      {children ? <p className="banner__text">{children}</p> : null}
      {actions ? <div className="actions">{actions}</div> : null}
    </div>
  );
}
