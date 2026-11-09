import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from './cx';

export interface PanelProps extends HTMLAttributes<HTMLElement> {
  as?: 'section' | 'div' | 'aside';
  tone?: 'default' | 'subtle';
  /** id заголовка панели */
  labelledBy?: string;
  children: ReactNode;
}

/** section.panel, вариант panel--subtle */
export function Panel({ as: Tag = 'section', tone = 'default', labelledBy, className, children, ...rest }: PanelProps) {
  return (
    <Tag {...rest} className={cx('panel', tone === 'subtle' && 'panel--subtle', className)} aria-labelledby={labelledBy}>
      {children}
    </Tag>
  );
}
