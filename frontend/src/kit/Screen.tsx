import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from './cx';

export type ScreenProps = HTMLAttributes<HTMLDivElement>;

/** div.screen: контейнер запросов, порог 800 px задан в kit.css */
export function Screen({ className, children, ...rest }: ScreenProps) {
  return (
    <div {...rest} className={cx('screen', className)}>
      {children}
    </div>
  );
}

export interface LayoutProps extends Omit<HTMLAttributes<HTMLElement>, 'children' | 'content'> {
  aside: ReactNode;
  content: ReactNode;
  /** На странице один main; в рамках витрины — div */
  as?: 'main' | 'div';
}

/** main.layout > div.layout__aside + div.layout__content */
export function Layout({ aside, content, as: Tag = 'main', className, ...rest }: LayoutProps) {
  return (
    <Tag {...rest} className={cx('layout', className)}>
      <div className="layout__aside">{aside}</div>
      <div className="layout__content">{content}</div>
    </Tag>
  );
}
