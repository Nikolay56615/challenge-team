import type { HTMLAttributes, ReactNode, Ref } from 'react';
import { cx } from './cx';

export interface BannerProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title' | 'children' | 'role'> {
  tone: 'info' | 'error';
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  /** Экран прокручивает к началу баннера, когда фокус уходит на карточку под ним (docs/ui-kit.md, 4.1) */
  ref?: Ref<HTMLDivElement> | undefined;
}

/** Строка роли над заголовком ошибки: роль видна текстом, а не только цветом (docs/ui-kit.md, D03) */
export const ERROR_KICKER = 'Ошибка';

/** div.banner: информационный — role="status", ошибка — role="alert" со строкой роли «Ошибка». Фокус не переносится. */
export function Banner({ tone, title, children, actions, className, ...rest }: BannerProps) {
  return (
    <div {...rest} className={cx('banner', `banner--${tone}`, className)} role={tone === 'error' ? 'alert' : 'status'}>
      {tone === 'error' ? <p className="banner__kicker">{ERROR_KICKER}</p> : null}
      <p className="banner__title">{title}</p>
      {children ? <p className="banner__text">{children}</p> : null}
      {actions ? <div className="actions">{actions}</div> : null}
    </div>
  );
}
