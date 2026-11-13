import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from './cx';
import { Tag } from './Tag';

export interface TopBarProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  brand: string;
  tag?: string;
  navigation?: ReactNode;
}

/** header.topbar > div.topbar__brand + Tag. Марка без ссылки. */
export function TopBar({ brand, tag, navigation, className, ...rest }: TopBarProps) {
  return (
    <header {...rest} className={cx('topbar', className)}>
      <div className="topbar__brand">
        <span className="topbar__logo" aria-hidden="true" />
        {brand}
      </div>
      {navigation}
      {tag ? <Tag>{tag}</Tag> : null}
    </header>
  );
}
