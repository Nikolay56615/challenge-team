import { useId, type HTMLAttributes } from 'react';
import { cx } from './cx';

export interface MatchChipsProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  /** Видимая подпись списка, она же его доступное имя */
  label?: string;
  /** Короткие подписи без чисел; пустой список — компонент ничего не выводит */
  items: readonly string[];
}

/**
 * div.match > span.match__label + ul.match__list > li.match__chip. Статичные пометки, а не элементы
 * управления: без рамки, наведения и минимальной высоты 44 px. Галочка нарисована в kit.css и стоит
 * только рядом с текстом (docs/ui-kit.md, раздел 3).
 */
export function MatchChips({ label = 'Совпало', items, className, ...rest }: MatchChipsProps) {
  const labelId = useId();
  if (items.length === 0) return null;
  return (
    <div {...rest} className={cx('match', className)}>
      {/* Подпись видна и называет список через aria-labelledby; сама по себе не озвучивается, иначе «Совпало» прозвучит дважды */}
      <span id={labelId} className="match__label" aria-hidden="true">
        {label}
      </span>
      <ul className="match__list" aria-labelledby={labelId}>
        {items.map((item) => (
          <li key={item} className="match__chip">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}
