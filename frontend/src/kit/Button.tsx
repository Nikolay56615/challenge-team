import type { ButtonHTMLAttributes, Ref } from 'react';
import { cx } from './cx';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'link';
export type ButtonSize = 'md' | 'sm';

export function buttonClass(variant: ButtonVariant, size: ButtonSize, extra?: string): string {
  return cx('btn', `btn--${variant}`, size === 'sm' && 'btn--sm', extra);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  ref?: Ref<HTMLButtonElement> | undefined;
}

/** button.btn. Занятое состояние передаётся через aria-disabled, чтобы кнопка не теряла фокус. */
export function Button({ variant = 'secondary', size = 'md', type = 'button', className, ...rest }: ButtonProps) {
  return <button type={type} className={buttonClass(variant, size, className)} {...rest} />;
}
