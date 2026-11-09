import type { HTMLAttributes, ReactNode, Ref } from 'react';
import { cx } from './cx';

export interface StatusLineProps extends HTMLAttributes<HTMLParagraphElement> {
  children?: ReactNode;
  ref?: Ref<HTMLParagraphElement> | undefined;
}

/** p.status-line с role="status" и aria-live="polite" */
export function StatusLine({ className, children, ...rest }: StatusLineProps) {
  return (
    <p {...rest} className={cx('status-line', className)} role="status" aria-live="polite">
      {children}
    </p>
  );
}
