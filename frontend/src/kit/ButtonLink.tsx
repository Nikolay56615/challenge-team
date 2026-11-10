import type { AnchorHTMLAttributes, ReactNode } from 'react';
import { buttonClass, type ButtonSize, type ButtonVariant } from './Button';

const ALLOWED_PROTOCOLS = new Set(['http:', 'https:']);

/** Абсолютный адрес http или https; иначе null. */
export function safeHttpUrl(href: string | null | undefined): string | null {
  if (!href) return null;
  try {
    const url = new URL(href);
    return ALLOWED_PROTOCOLS.has(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

export interface ButtonLinkProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href' | 'children'> {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Открыть в новой вкладке с rel="noopener noreferrer" */
  external?: boolean;
  children: ReactNode;
}

/** a.btn. Ссылка с другой схемой, кроме http и https, не выводится. */
export function ButtonLink({ href, variant = 'secondary', size = 'md', external = false, className, children, ...rest }: ButtonLinkProps) {
  const safeHref = safeHttpUrl(href);
  if (!safeHref) return null;
  return (
    <a
      {...rest}
      href={safeHref}
      className={buttonClass(variant, size, className)}
      target={external ? '_blank' : undefined}
      rel={external ? 'noopener noreferrer' : undefined}
    >
      {children}
      {external && <span className="visually-hidden"> (откроется в новой вкладке)</span>}
    </a>
  );
}
