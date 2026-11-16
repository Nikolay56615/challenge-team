import { useEffect, useState } from 'react';
import { getModelCard } from '../api/client';
import type { ModelCard } from '../api/types';
import { formatScore, formatShare } from '../feed';
import { plural, typo } from '../format';
import { Disclosure } from '../kit';

/**
 * Паспорт модели: чем проверена лента и что получилось. Числа приходят из `GET /api/model-card`, их пишет
 * офлайн-оценка на журнале записей. Вывод читатель делает сам: рядом стоят лента, совместные записи и популярность.
 * Без записанного паспорта блок не показывается.
 */
export function ModelPassport() {
  const [card, setCard] = useState<ModelCard | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getModelCard(controller.signal)
      .then(setCard)
      .catch(() => {
        // Паспорт — справка: без него лента работает, поэтому сбой не показывается ошибкой
      });
    return () => {
      controller.abort();
    };
  }, []);

  if (!card) return null;
  return (
    <Disclosure summary="Паспорт модели">
      <p className="field__hint">{typo(`${card.data}.`)}</p>
      {card.groups.map((group) => (
        <table key={group.code} className="compare-table passport-table">
          <caption>
            {typo(
              `${group.label}: ${group.users.toLocaleString('ru-RU')} ${plural(group.users, { one: 'пользователь', few: 'пользователя', many: 'пользователей' })}`,
            )}
          </caption>
          <thead>
            <tr>
              <th scope="col">Метод</th>
              <th scope="col">Первый среди курсов</th>
              <th scope="col">В&nbsp;первых пяти курсах</th>
            </tr>
          </thead>
          <tbody>
            {group.rows.map((row) => (
              <tr key={row.method}>
                <th scope="row">{row.label}</th>
                <td>{formatShare(row.hit1)}</td>
                <td>{formatShare(row.hit5)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
      <h3 className="feed-aside__subtitle">Свойства ленты</h3>
      <ul className="share-list">
        {card.feed.map((entry) => (
          <li key={entry.label} className="share-list__row">
            <span>{typo(entry.label)}</span>
            <span className="share-list__value">
              {entry.share ? formatShare(entry.value) : formatScore(entry.value)}
            </span>
          </li>
        ))}
      </ul>
      <h3 className="feed-aside__subtitle">Веса источников</h3>
      <ul className="share-list">
        {card.weights.map((entry) => (
          <li key={entry.label} className="share-list__row">
            <span>{typo(entry.label)}</span>
            <span className="share-list__value">{formatScore(entry.value)}</span>
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}
