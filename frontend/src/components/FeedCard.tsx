import { useId, useState } from 'react';
import type { FeedItem } from '../api/types';
import { FAMILY_LABEL, FAMILY_OF, clientReason, formatScore, scoreLabel, segments } from '../feed';
import { formatDuration, typo } from '../format';
import { Badge, Button, ButtonLink, Card, RankMarker, cx } from '../kit';
import { CompareTable } from './CompareTable';

export interface FeedCardProps {
  item: FeedItem;
  /** Наибольшая оценка в ленте: от неё отсчитывается длина полосы */
  topScore: number;
  /** Карточка для сравнения в деталях: первая для всех остальных, последняя для первой */
  reference: FeedItem | null;
  /** Сдвиг места после «что если»: число мест вверх, null — новая карточка, undefined — без изменений */
  shift?: number | null | undefined;
  onComplete: (item: FeedItem) => void;
  disabled: boolean;
  /** Вид клиента: название, строка сведений и причина, без оценки и расчёта */
  plain?: boolean;
}

function shiftLabel(shift: number | null): { text: string; label: string } {
  if (shift === null) return { text: 'новая', label: 'Карточки раньше не было в\u00A0ленте' };
  const places = String(Math.abs(shift));
  return shift > 0
    ? { text: `▲ ${places}`, label: `Поднялась на ${places}` }
    : { text: `▼ ${places}`, label: `Опустилась на ${places}` };
}

/** Полоса оценки: длина — доля от лучшей оценки ленты, сегменты — вклады по группам источников */
function ScoreBar({ item, topScore }: { item: FeedItem; topScore: number }) {
  const scale = topScore > 0 ? 100 / topScore : 0;
  return (
    <span className="score-bar" role="img" aria-label={scoreLabel(item)}>
      {segments(item).map((segment) => (
        <span
          key={segment.family}
          className={`score-bar__seg score-bar__seg--${segment.family}`}
          style={{ width: `${String(segment.value * scale)}%` }}
          title={`${FAMILY_LABEL[segment.family]}: ${formatScore(segment.value)}`}
        />
      ))}
    </span>
  );
}

/** Карточка ленты: название, строка сведений, одна причина и полоса оценки; расчёт открывается по запросу */
export function FeedCard({ item, topScore, reference, shift, onComplete, disabled, plain = false }: FeedCardProps) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const meta = [item.format_label, formatDuration(item.duration_minutes)].filter(Boolean).join(' · ');
  const moved = shift === undefined ? null : shiftLabel(shift);

  return (
    <Card label={`Место ${String(item.rank)}`} className="feed-card">
      <div className="feed-card__head">
        <RankMarker rank={item.rank} />
        <h3 className="feed-card__title">{typo(item.title)}</h3>
        {moved && !plain ? (
          <Badge tone="flag" aria-label={moved.label}>
            {moved.text}
          </Badge>
        ) : null}
      </div>
      <p className="feed-card__meta">
        {meta}
        {meta ? ' · ' : ''}
        <Badge tone={item.is_paid ? 'paid' : 'free'}>{item.access_label}</Badge>
        {item.flags.map((flag) => (
          <Badge key={flag.code} tone="flag">
            {flag.label}
          </Badge>
        ))}
      </p>
      {item.reason ? (
        <p className="feed-card__reason">{typo(plain ? clientReason(item.reason) : item.reason)}.</p>
      ) : null}
      {plain ? null : (
        <>
          <div className="score">
            <span className="score__value">Оценка {formatScore(item.score)}</span>
            <ScoreBar item={item} topScore={topScore} />
          </div>
          <div className="feed-card__actions">
            <Button
              variant="link"
              aria-expanded={open}
              aria-controls={detailsId}
              onClick={() => {
                setOpen((value) => !value);
              }}
            >
              {open ? 'Скрыть расчёт' : 'Как посчитано'}
            </Button>
          </div>
          <div id={detailsId} className="feed-details" hidden={!open}>
            {open ? (
              <>
                <p className="feed-details__title">Оценка {formatScore(item.score)} складывается из вкладов</p>
                <ul className="feed-parts">
                  {item.parts.map((part) => {
                    // Вычет в полосу не входит, поэтому у него пустой образец, как в легенде
                    const family = part.value > 0 ? FAMILY_OF[part.source] : null;
                    return (
                      <li key={part.source} className="feed-parts__row">
                        <span
                          className={cx('swatch', family ? `swatch--${family}` : 'swatch--none')}
                          aria-hidden="true"
                        />
                        <span className="feed-parts__label">{typo(part.label)}</span>
                        <span className="feed-parts__value">{formatScore(part.value)}</span>
                        <span className="feed-parts__evidence">
                          {part.evidence ? `${typo(part.evidence)}.` : ''}
                          {part.note ? <span className="feed-parts__note">{typo(part.note)}.</span> : null}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                {reference ? (
                  <CompareTable
                    caption={
                      reference.rank < item.rank ? 'Рядом с\u00A0первой карточкой' : 'Рядом с\u00A0последней карточкой'
                    }
                    a={item}
                    b={reference}
                  />
                ) : null}
                <p className="feed-details__step">Следующий шаг для клиента. {typo(item.next_step)}.</p>
                <div className="actions">
                  {item.link_allowed && item.url ? (
                    <ButtonLink href={item.url} variant="secondary" size="sm" external>
                      Открыть материал
                    </ButtonLink>
                  ) : null}
                  <Button
                    variant="link"
                    aria-disabled={disabled}
                    onClick={() => {
                      if (!disabled) onComplete(item);
                    }}
                  >
                    Отметить пройденным и&nbsp;пересчитать ленту
                  </Button>
                </div>
              </>
            ) : null}
          </div>
        </>
      )}
    </Card>
  );
}
