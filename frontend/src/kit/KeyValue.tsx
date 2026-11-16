import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from './cx';

export interface KeyValueProps extends HTMLAttributes<HTMLDivElement> {
  label: string;
  children: ReactNode;
}

/** div.kv > span.kv__label + span.kv__value */
export function KeyValue({ label, className, children, ...rest }: KeyValueProps) {
  return (
    <div {...rest} className={cx('kv', className)}>
      <span className="kv__label">{label}</span>
      <span className="kv__value">{children}</span>
    </div>
  );
}
