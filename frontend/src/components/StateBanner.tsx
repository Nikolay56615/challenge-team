import type { Ref } from 'react';
import type { Clarification, TopicCode } from '../api/types';
import { typo } from '../format';
import { Banner, Button, ChipGroup } from '../kit';

export const ERROR_TITLE = 'Не удалось получить подборку';
export const NETWORK_ERROR_TEXT = 'Сервис не ответил. Введённые данные сохранены.';

export type StateBannerProps =
  | {
      kind: 'clarification';
      clarification: Clarification;
      topic: TopicCode | null;
      onChooseTopic: (topic: TopicCode) => void;
      onDismiss: () => void;
      disabled?: boolean;
      /** Начало баннера: вопрос остаётся в окне, когда фокус уходит на первую карточку (docs/ui-kit.md, 4.1) */
      bannerRef?: Ref<HTMLDivElement>;
    }
  | {
      kind: 'error';
      /** Текст ответа сервиса или NETWORK_ERROR_TEXT */
      message: string;
      onRetry: () => void;
      /** «Повторить» принимает фокус, если повтор из области выдачи снова не удался */
      retryRef?: Ref<HTMLButtonElement>;
    };

/** Уточнение при слабом совпадении или ошибка запроса с «Повторить» */
export function StateBanner(props: StateBannerProps) {
  if (props.kind === 'error') {
    // Поля берутся из props до разметки: обращение props.retryRef при рендере правило react-hooks/refs считает чтением ref
    const { message, onRetry, retryRef } = props;
    return (
      <Banner
        tone="error"
        title={ERROR_TITLE}
        actions={
          <Button ref={retryRef} variant="primary" size="sm" onClick={onRetry}>
            Повторить
          </Button>
        }
      >
        {typo(message)}
      </Banner>
    );
  }

  const { clarification, topic, onChooseTopic, onDismiss, disabled = false, bannerRef } = props;
  return (
    <Banner
      ref={bannerRef}
      tone="info"
      title={typo(clarification.question)}
      actions={
        <>
          {clarification.options.length > 0 ? (
            <ChipGroup
              legend="Тема"
              legendHidden
              name="clarification-topic"
              options={clarification.options}
              value={topic}
              onChange={(value) => {
                if (value) onChooseTopic(value);
              }}
              allowDeselect={false}
              activation="manual"
              disabled={disabled}
            />
          ) : null}
          <Button variant="link" onClick={onDismiss} disabled={disabled}>
            Оставить как есть
          </Button>
        </>
      }
    >
      {typo(clarification.text)}
    </Banner>
  );
}
