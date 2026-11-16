import { useState, type DetailsHTMLAttributes, type ReactNode } from 'react';
import { cx } from './cx';

export interface DisclosureProps extends Omit<DetailsHTMLAttributes<HTMLDetailsElement>, 'open' | 'children'> {
  summary: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}

/** details.disclosure > summary + div.disclosure__body. Нативное раскрытие, стрелка ▾ или ▸ из kit.css. */
export function Disclosure({ summary, defaultOpen = false, className, onToggle, children, ...rest }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      {...rest}
      className={cx('disclosure', className)}
      open={open}
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
        onToggle?.(event);
      }}
    >
      <summary>{summary}</summary>
      <div className="disclosure__body">{children}</div>
    </details>
  );
}
