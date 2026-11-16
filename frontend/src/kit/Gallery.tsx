// Витрина UI-кита: каждый компонент во всех вариантах и состояниях (docs/ui-kit.md, раздел 6).
// Параметр ?only=<id> показывает один раздел, например ?only=screen-cards.
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { CompareView, compareStatus, type CompareTab } from '../components/CompareView';
import { DemoPanel } from '../components/DemoPanel';
import { EmptyState, STARTER_VISIBLE } from '../components/EmptyState';
import { IntroPanel } from '../components/IntroPanel';
import { MaterialCard } from '../components/MaterialCard';
import { LOADING_STATUS, ResultList } from '../components/ResultList';
import { RouteBlock } from '../components/RouteBlock';
import { NETWORK_ERROR_TEXT, StateBanner } from '../components/StateBanner';
import { TaskForm } from '../components/TaskForm';
import type { CompareResponse, IndustryCode, RecommendResponse, StageCode, TopicCode } from '../api/types';
import { EMPTY_FORM, type FormValues } from '../state/useRecommend';
import {
  Badge,
  Banner,
  Button,
  ButtonLink,
  Card,
  Checkbox,
  ChipGroup,
  Disclosure,
  KeyValue,
  Layout,
  MatchChips,
  Panel,
  RankMarker,
  Screen,
  SelectField,
  Skeleton,
  SKELETON_DELAY_MS,
  StatusLine,
  TabPanel,
  Tabs,
  Tag,
  TextAreaField,
  TextField,
  TopBar,
} from './index';
import * as S from './samples';

const ONLY = new URLSearchParams(window.location.search).get('only');

/** Раздел виден без фильтра, при совпадении id или при фильтре по вложенному разделу */
function show(id: string): boolean {
  return !ONLY || ONLY === id || id.startsWith(`${ONLY}-`) || ONLY.startsWith(`${id}-`);
}

const noop = () => {
  // Витрина показывает состояния без действий: обработчик ничего не делает
};

const COLOR_TOKENS = [
  '--color-ink',
  '--color-muted',
  '--color-bg',
  '--color-surface',
  '--color-surface-subtle',
  '--color-surface-disabled',
  '--color-line',
  '--color-line-strong',
  '--color-accent',
  '--color-accent-hover',
  '--color-accent-soft',
  '--color-accent-ink',
  '--color-accent-line',
  '--color-topic-bg',
  '--color-neutral-bg',
  '--color-neutral-ink',
  '--color-ok-bg',
  '--color-ok-ink',
  '--color-paid-bg',
  '--color-paid-ink',
  '--color-flag-bg',
  '--color-flag-ink',
  '--color-err-bg',
  '--color-err-ink',
  '--color-skeleton-a',
  '--color-skeleton-b',
  '--color-focus',
] as const;

const SPACE_TOKENS = ['--space-1', '--space-2', '--space-3', '--space-4', '--space-5', '--space-6'] as const;
const RADIUS_TOKENS = ['--radius-sm', '--radius-md', '--radius-field', '--radius-lg', '--radius-xl', '--radius-pill'] as const;
const ALL_TOKENS = [...COLOR_TOKENS, ...SPACE_TOKENS, ...RADIUS_TOKENS];

/** Значения токенов читаются из tokens.css, а не дублируются */
function useTokenValues(): Record<string, string> {
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    const style = getComputedStyle(document.documentElement);
    // Значения приходят из CSSOM, внешнего для React источника, один раз после монтирования; подписки нет
    // eslint-disable-next-line react-hooks/set-state-in-effect -- чтение стилей документа после монтирования
    setValues(Object.fromEntries(ALL_TOKENS.map((name) => [name, style.getPropertyValue(name).trim()])));
  }, []);
  return values;
}

// ---------- обвязка витрины ----------
function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  if (!show(id)) return null;
  return (
    <section id={id} className="kit-section" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className="h1">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Specimen({ id, title, note, children }: { id: string; title: string; note?: string; children: ReactNode }) {
  if (!show(id)) return null;
  return (
    <Panel id={id} labelledBy={`${id}-title`}>
      <h3 id={`${id}-title`} className="h2">
        {title}
      </h3>
      {note ? <p className="hint">{note}</p> : null}
      {children}
    </Panel>
  );
}

function Variant({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="kit-stack kit-stack--tight">
      <span className="hint">{label}</span>
      {children}
    </div>
  );
}

const FRAME_WIDTHS = [390, 1120] as const;
type FrameWidth = (typeof FRAME_WIDTHS)[number];

/** Рамки .kit-frame.screen шириной 390 и 1120 px: внутри работают контейнерные запросы */
function Frames({ id, title, note, children }: { id: string; title: string; note?: string; children: (width: FrameWidth) => ReactNode }) {
  if (!show(id)) return null;
  return (
    <section id={id} className="kit-section" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className="h2">
        {title}
      </h3>
      {note ? <p className="hint">{note}</p> : null}
      {/* Ряд рамок прокручивается по горизонтали: tabIndex даёт прокрутку с клавиатуры (axe scrollable-region-focusable) */}
      <div className="kit-frames" role="region" aria-label={`${title}: рамки 390 и 1120 px`} tabIndex={0}>
        {FRAME_WIDTHS.map((width) => (
          <figure key={width} className="kit-figure">
            <figcaption className="hint">{width === 390 ? 'Мобильный · 390 px' : 'Настольный · 1120 px'}</figcaption>
            <Screen className="kit-frame" style={{ width }}>
              {children(width)}
            </Screen>
          </figure>
        ))}
      </div>
    </section>
  );
}

function FrameBody({ children }: { children: ReactNode }) {
  return <div className="kit-frame__body">{children}</div>;
}

// ---------- интерактивные образцы ----------
function ChipGroupDemo() {
  const [stage, setStage] = useState<StageCode | null>(null);
  const [selected, setSelected] = useState<StageCode | null>('start');
  const [topic, setTopic] = useState<TopicCode | null>(null);
  return (
    <>
      <Variant label="Не выбран">
        <ChipGroup
          legend="Стадия бизнеса"
          optional
          name="kit-stage-a"
          options={S.META.stages}
          value={stage}
          onChange={(value) => {
            setStage(value);
          }}
        />
      </Variant>
      <Variant label="Выбран: повторное нажатие снимает выбор">
        <ChipGroup
          legend="Стадия бизнеса"
          optional
          name="kit-stage-b"
          options={S.META.stages}
          value={selected}
          onChange={(value) => {
            setSelected(value);
          }}
        />
      </Variant>
      <Variant label="disabled">
        <ChipGroup
          legend="Стадия бизнеса"
          optional
          name="kit-stage-c"
          options={S.META.stages}
          value="growth"
          onChange={noop}
          disabled
        />
      </Variant>
      <Variant label="Темы уточнения: скрытая легенда, activation=manual — стрелки переносят фокус, выбирают щелчок, пробел и Enter">
        <ChipGroup
          legend="Тема"
          legendHidden
          name="kit-topic"
          options={S.COLD.clarification?.options ?? []}
          value={topic}
          onChange={(value) => {
            setTopic(value);
          }}
          allowDeselect={false}
          activation="manual"
        />
      </Variant>
    </>
  );
}

function TextAreaDemo() {
  const [empty, setEmpty] = useState('');
  const [filled, setFilled] = useState(S.PROFILES[0]?.task ?? '');
  const [limit, setLimit] = useState(S.LIMIT_TASK);
  const [paste, setPaste] = useState(S.LIMIT_TASK.slice(0, 290));
  return (
    <>
      <TextAreaField
        id="kit-task-empty"
        label="Пусто: подсказка"
        value={empty}
        onChange={setEmpty}
        maxLength={300}
        placeholder="Например: запустить первую рекламу"
        hint="До 300 символов. Можно своими словами, без терминов"
      />
      <TextAreaField id="kit-task-filled" label="Заполнено: счётчик" value={filled} onChange={setFilled} maxLength={300} />
      <TextAreaField
        id="kit-task-disabled"
        label="disabled: идёт подбор"
        value={S.PROFILES[0]?.task ?? ''}
        onChange={noop}
        maxLength={300}
        disabled
      />
      <TextAreaField
        id="kit-task-error"
        label="Ошибка и счётчик"
        value={S.PROFILES[1]?.task ?? ''}
        onChange={noop}
        maxLength={300}
        error="Запрос длиннее 300 символов"
      />
      <TextAreaField id="kit-task-limit" label="У предела: 300 из 300 символов" value={limit} onChange={setLimit} maxLength={300} />
      <TextAreaField
        id="kit-task-paste"
        label="Вставка длиннее остатка: вставьте сюда текст длиннее 10 символов"
        value={paste}
        onChange={setPaste}
        maxLength={300}
      />
    </>
  );
}

function TextFieldDemo() {
  const [code, setCode] = useState('');
  const [filled, setFilled] = useState('U0239');
  return (
    <>
      <TextField
        id="kit-code-empty"
        label="Код клиента: с действием"
        value={code}
        onChange={setCode}
        action={<Button variant="secondary">Найти</Button>}
        hint="В списке первые 50 из 7 342 клиентов."
      />
      <TextField
        id="kit-code-error"
        label="Ошибка"
        value={filled}
        onChange={setFilled}
        error="Клиента с кодом «U0239» нет в журнале"
      />
      <TextField id="kit-code-disabled" label="disabled" value="U0008" onChange={noop} disabled />
    </>
  );
}

function SelectDemo() {
  const [industry, setIndustry] = useState<IndustryCode | null>(null);
  const [chosen, setChosen] = useState<IndustryCode | null>('horeca');
  const [profile, setProfile] = useState<string | null>(S.PROFILES[0]?.id ?? null);
  const profiles = S.PROFILES.map((p) => ({ value: p.id, label: p.label }));
  return (
    <>
      <SelectField
        id="kit-industry-empty"
        label="Сфера бизнеса"
        optional
        value={industry}
        onChange={(value) => {
          setIndustry(value);
        }}
        options={S.META.industries}
        emptyLabel="Не указана"
      />
      <SelectField
        id="kit-industry-chosen"
        label="Сфера бизнеса: выбрано"
        optional
        value={chosen}
        onChange={(value) => {
          setChosen(value);
        }}
        options={S.META.industries}
        emptyLabel="Не указана"
      />
      <SelectField
        id="kit-profile"
        label="Компактный с подсказкой: тестовый профиль"
        value={profile}
        onChange={setProfile}
        options={profiles}
        emptyLabel="Не выбран"
        hint={S.PROFILES.find((p) => p.id === profile)?.description}
        compact
      />
      <SelectField
        id="kit-industry-disabled"
        label="disabled"
        value="horeca"
        onChange={noop}
        options={S.META.industries}
        emptyLabel="Не указана"
        disabled
      />
    </>
  );
}

function CheckboxDemo() {
  const [on, setOn] = useState(true);
  const [off, setOff] = useState(false);
  return (
    <div className="kit-stack">
      <Checkbox checked={on} onChange={setOn} label="Отмечен: сравнить с подбором по теме" />
      <Checkbox checked={off} onChange={setOff} label="Не отмечен" />
      <Checkbox checked onChange={noop} label="disabled, отмечен" disabled />
      <Checkbox checked={false} onChange={noop} label="disabled, не отмечен" disabled />
    </div>
  );
}

const KIT_TABS = [
  { id: 'kit-tabs-baseline', label: 'Подбор по теме' },
  { id: 'kit-tabs-personal', label: 'Персональный подбор' },
] as const;

function TabsDemo() {
  const [selected, setSelected] = useState<string>(KIT_TABS[1].id);
  return (
    <>
      <Tabs ariaLabel="Метод подбора" tabs={KIT_TABS} selected={selected} onSelect={setSelected} />
      <TabPanel tabId={KIT_TABS[0].id} hidden={selected !== KIT_TABS[0].id}>
        <p className="compare__sub">Панель подбора по теме: порядок одинаков для всех профилей с этой темой.</p>
      </TabPanel>
      <TabPanel tabId={KIT_TABS[1].id} hidden={selected !== KIT_TABS[1].id}>
        <p className="compare__sub">Панель персонального подбора: стрелки, Home и End переключают вкладки.</p>
      </TabPanel>
    </>
  );
}

function ScreenDemo() {
  const first = S.PROFILES[0];
  const [values, setValues] = useState<FormValues>(
    first
      ? { task: first.task, stage: first.stage, experience: first.experience, format_pref: first.format_pref, industry: first.industry }
      : EMPTY_FORM,
  );
  const [profileId, setProfileId] = useState<string | null>(first?.id ?? null);
  const [compare, setCompare] = useState(false);
  return (
    <>
      <TopBar brand="Учебная платформа" tag="Демо-данные" />
      <Layout
        as="div"
        aside={
          <>
            <TaskForm
              meta={S.META}
              values={values}
              maxLength={S.META.max_task_length}
              error={null}
              loading={false}
              onTaskChange={(task) => {
                setValues((prev) => ({ ...prev, task }));
              }}
              onRefinementsChange={(patch) => {
                setValues((prev) => ({ ...prev, ...patch }));
              }}
              onSubmit={noop}
              onReset={() => {
                setValues(EMPTY_FORM);
                setProfileId(null);
              }}
            />
            <DemoPanel
              profiles={S.PROFILES}
              profileId={profileId}
              onSelectProfile={setProfileId}
              compare={compare}
              onCompareChange={setCompare}
            />
          </>
        }
        content={<ResultList status={S.STRONG.message} response={S.STRONG} onComplete={noop} onMore={noop} />}
      />
    </>
  );
}

function LoadingDemo() {
  const first = S.PROFILES[0];
  const values: FormValues = first
    ? { task: first.task, stage: first.stage, experience: first.experience, format_pref: first.format_pref, industry: first.industry }
    : EMPTY_FORM;
  return (
    <>
      <TopBar brand="Учебная платформа" tag="Демо-данные" />
      <Layout
        as="div"
        aside={
          <TaskForm
            meta={S.META}
            values={values}
            maxLength={S.META.max_task_length}
            error={null}
            loading
            onTaskChange={noop}
            onRefinementsChange={noop}
            onSubmit={noop}
            onReset={noop}
          />
        }
        content={<ResultList status={LOADING_STATUS} loading />}
      />
    </>
  );
}

/** Загрузка до истечения задержки скелетонов: строка состояния сразу, прежняя выдача на месте, неактивная (D10) */
function StaleDemo() {
  return (
    <FrameBody>
      <ResultList status={LOADING_STATUS} stale response={S.STRONG} showTopics={false} onComplete={noop} onMore={noop} />
    </FrameBody>
  );
}

/** Слабое совпадение в контексте: баннер с темами, строка состояния, смешанная выдача с бейджами тем */
function WeakDemo() {
  const [topic, setTopic] = useState<TopicCode | null>(null);
  const clarification = S.WEAK.clarification;
  return (
    <FrameBody>
      {clarification ? (
        <StateBanner
          kind="clarification"
          clarification={clarification}
          topic={topic}
          onChooseTopic={setTopic}
          onDismiss={noop}
        />
      ) : null}
      <ResultList status={S.WEAK.message} response={S.WEAK} showTopics onComplete={noop} onMore={noop} />
    </FrameBody>
  );
}

/** Пустая выдача: «Показать все N» раскрывает подборку, фокус — на первую раскрытую карточку */
function EmptyDemo({ response }: { response: RecommendResponse }) {
  const [expanded, setExpanded] = useState(false);
  const [topic, setTopic] = useState<TopicCode | null>(null);
  const cardRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (expanded) cardRef.current?.focus();
  }, [expanded]);
  return (
    <FrameBody>
      <EmptyState
        response={response}
        topic={topic}
        onChooseTopic={setTopic}
        onComplete={noop}
        expanded={expanded}
        onExpand={() => {
          setExpanded(true);
        }}
        focusIndex={STARTER_VISIBLE}
        cardRef={cardRef}
      />
    </FrameBody>
  );
}

/**
 * Сравнение: на узком экране сначала открыта вкладка initialTab. Над представлением — текст строки состояния:
 * в приложении она скрыта и итог сравнения слышен только с экранным диктором.
 */
function CompareDemo({ response, initialTab = 'personal' }: { response: CompareResponse; initialTab?: CompareTab }) {
  const [tab, setTab] = useState<CompareTab>(initialTab);
  return (
    <FrameBody>
      <p className="hint">Строка состояния для экранного диктора: «{compareStatus(response)}»</p>
      <CompareView response={response} onComplete={noop} tab={tab} onTabChange={setTab} />
    </FrameBody>
  );
}

// ---------- страница ----------
export function Gallery() {
  const tokens = useTokenValues();
  const swatch = (name: string): CSSProperties => ({ background: `var(${name})` });

  return (
    <main className="kit-page">
      <header className="kit-page__head">
        <h1 className="h1">UI-кит трека 1 · витрина</h1>
        <p className="lead">
          Базовые компоненты и компоненты экрана во всех вариантах и состояниях. Пропсы описаны в типах
          компонентов в папках frontend/src/kit и frontend/src/components.
          Данные вымышленные: синтетический каталог.
        </p>
      </header>

      <Section id="tokens" title="2. Токены">
        <Specimen id="tokens-color" title="2.1 Цвет" note="Значения прочитаны из tokens.css.">
          <div className="kit-swatches">
            {COLOR_TOKENS.map((name) => (
              <div key={name} className="kit-swatch">
                <span className="kit-swatch__chip" style={swatch(name)} aria-hidden="true" />
                <span className="kit-stack kit-stack--tight">
                  <code>{name}</code>
                  <span className="hint">{tokens[name] ?? ''}</span>
                </span>
              </div>
            ))}
          </div>
        </Specimen>
        <Specimen id="tokens-type" title="2.2 Типографика" note="Onest, локальные woff2 для кириллицы и латиницы: внешние CDN не нужны.">
          <p className="h1">Заголовок экрана · --font-size-h1, 30 px</p>
          <p className="h2">Заголовок панели · --font-size-h2, 20 px</p>
          <p className="h3">Название материала · --font-size-h3, 17 px</p>
          <p>Основной текст и поле задачи · --font-size-base, 16 px</p>
          <p className="status-line">Строка состояния, чипы, значения карточки · --font-size-sm, 15 px</p>
          <p className="hint">Подсказки и примечания · --font-size-xs, 13 px</p>
          <span className="kv__label">Подписи блоков карточки · --font-size-2xs, 12 px</span>
        </Specimen>
        <Specimen id="tokens-space" title="2.3 Отступы, радиусы, тень">
          <div className="kit-stack">
            {SPACE_TOKENS.map((name) => (
              <div key={name} className="kit-row">
                <span className="kit-measure" style={{ width: `var(${name})` }} aria-hidden="true" />
                <code>{name}</code>
                <span className="hint">{tokens[name] ?? ''}</span>
              </div>
            ))}
          </div>
          <div className="kit-row">
            {RADIUS_TOKENS.map((name) => (
              <div key={name} className="kit-stack kit-stack--tight">
                <span className="kit-radius" style={{ borderRadius: `var(${name})` }} aria-hidden="true" />
                <code>{name}</code>
                <span className="hint">{tokens[name] ?? ''}</span>
              </div>
            ))}
          </div>
        </Specimen>
      </Section>

      <Section id="base" title="3. Базовые компоненты">
        <div className="kit-grid">
          <Specimen id="base-button" title="Button">
            <Variant label="primary, secondary, outline, link: ссылка-кнопка в цвете текста с подчёркиванием">
              <div className="kit-row">
                <Button variant="primary">Подобрать материалы</Button>
                <Button variant="secondary">Показать ещё 3</Button>
                <Button variant="outline">Открыть страницу курса</Button>
                <Button variant="link">Сбросить</Button>
              </div>
            </Variant>
            <Variant label="Размер sm">
              <div className="kit-row">
                <Button variant="primary" size="sm">
                  Повторить
                </Button>
                <Button variant="secondary" size="sm">
                  Открыть материал
                </Button>
                <Button variant="outline" size="sm">
                  Открыть страницу курса
                </Button>
                <Button variant="link" size="sm">
                  Отметить изученным
                </Button>
              </div>
            </Variant>
            <Variant label="disabled">
              <div className="kit-row">
                <Button variant="primary" disabled>
                  Подобрать материалы
                </Button>
                <Button variant="secondary" disabled>
                  Показать ещё 3
                </Button>
                <Button variant="outline" disabled>
                  Открыть страницу курса
                </Button>
                <Button variant="link" disabled>
                  Сбросить
                </Button>
              </div>
            </Variant>
            <Variant label="Занято: aria-disabled, фокус сохраняется">
              <div className="kit-row">
                <Button variant="primary" aria-disabled>
                  Подбираем…
                </Button>
              </div>
            </Variant>
          </Specimen>

          <Specimen id="base-link" title="ButtonLink" note="Внешняя ссылка: новая вкладка, rel=noopener noreferrer, скрытая подпись. Схемы, кроме http и https, не выводятся.">
            <div className="kit-row">
              <ButtonLink href="https://example.org/materials/m01" external size="sm">
                Открыть материал
              </ButtonLink>
              <ButtonLink href="https://example.org/courses/m02" external variant="outline" size="sm">
                Открыть страницу курса
              </ButtonLink>
              <ButtonLink href="https://example.org/materials/m03" external variant="outline">
                Открыть страницу материала
              </ButtonLink>
            </div>
            <Variant label="ftp://example.org — ссылка не выводится">
              <div className="kit-row">
                <ButtonLink href="ftp://example.org/file" external size="sm">
                  Не должна появиться
                </ButtonLink>
                <span className="note">Кнопки нет</span>
              </div>
            </Variant>
          </Specimen>

          <Specimen id="base-chips" title="ChipGroup">
            <ChipGroupDemo />
          </Specimen>

          <Specimen id="base-badge" title="Badge">
            <Variant label="neutral, free, paid, flag, topic">
              <div className="badges">
                <Badge>Чек-лист</Badge>
                <Badge>15 мин</Badge>
                <Badge>Для начинающих</Badge>
                <Badge tone="free">Бесплатно</Badge>
                <Badge tone="paid">Платно</Badge>
                <Badge tone="paid">По подписке</Badge>
                <Badge tone="flag">Вы уже открывали</Badge>
                <Badge tone="flag">В процессе</Badge>
                <Badge tone="flag">Пройдено</Badge>
                <Badge tone="topic">Продвижение</Badge>
              </div>
            </Variant>
          </Specimen>

          <Specimen id="base-panel" title="Panel">
            <Panel labelledBy="kit-panel-default">
              <p id="kit-panel-default" className="h2">
                Панель по умолчанию
              </p>
              <p className="lead">Фон surface, рамка line, радиус lg. Заголовок связан через aria-labelledby.</p>
            </Panel>
            <Panel tone="subtle" labelledBy="kit-panel-subtle">
              <div className="panel__row">
                <span id="kit-panel-subtle" className="kv__label">
                  Демо-режим
                </span>
                <span className="hint">только в локальном стенде</span>
              </div>
              <p>Вариант subtle: демо-панель.</p>
            </Panel>
          </Specimen>

          <Specimen id="base-card" title="Card, RankMarker, KeyValue">
            <Card label="Позиция 1">
              <div className="card__head">
                <RankMarker rank={1} />
                <p className="h3 card__title">{S.M01.title}</p>
              </div>
              <KeyValue label="Почему подходит">Тема «Продвижение» совпадает с задачей.</KeyValue>
              <KeyValue label="Следующий шаг">Отметьте три пункта, которые сделаете на этой неделе.</KeyValue>
            </Card>
            <Variant label="RankMarker">
              <div className="kit-row">
                <RankMarker rank={1} />
                <RankMarker rank={2} />
                <RankMarker rank={10} />
              </div>
            </Variant>
          </Specimen>

          <Specimen id="base-banner" title="Banner">
            <Banner
              tone="info"
              title="Уточните тему"
              actions={
                <>
                  <ChipGroup
                    legend="Тема"
                    legendHidden
                    name="kit-banner-topic"
                    options={S.WEAK_CLARIFICATION.options}
                    value={null}
                    onChange={noop}
                    allowDeselect={false}
                    activation="manual"
                  />
                  <Button variant="link">Оставить как есть</Button>
                </>
              }
            >
              Информационный: role=&quot;status&quot;, нейтральная поверхность, светлая рамка и акцентная полоса слева. Фокус не переносится.
            </Banner>
            <Banner
              tone="error"
              title="Не удалось получить подборку"
              actions={
                <Button variant="primary" size="sm">
                  Повторить
                </Button>
              }
            >
              Ошибка: role=&quot;alert&quot;, строка роли «Ошибка» над заголовком, сплошная рамка 2 px цвета ошибки.
            </Banner>
          </Specimen>

          <Specimen id="base-textarea" title="TextAreaField">
            <TextAreaDemo />
          </Specimen>

          <Specimen id="base-textfield" title="TextField">
            <TextFieldDemo />
          </Specimen>

          <Specimen id="base-select" title="SelectField">
            <SelectDemo />
          </Specimen>

          <Specimen id="base-checkbox" title="Checkbox">
            <CheckboxDemo />
          </Specimen>

          <Specimen id="base-tabs" title="Tabs, TabPanel" note="Только на узком экране сравнения.">
            <TabsDemo />
          </Specimen>

          <Specimen id="base-disclosure" title="Disclosure">
            <Disclosure defaultOpen summary="Открыт">
              <p className="hint">Содержимое видно, стрелка ▾.</p>
            </Disclosure>
            <Disclosure summary="Закрыт">
              <p className="hint">Содержимое скрыто, стрелка ▸.</p>
            </Disclosure>
          </Specimen>

          <Specimen
            id="base-skeleton"
            title="Skeleton, StatusLine"
            note={`Строка состояния появляется сразу. Скелетоны экрана — через ${String(SKELETON_DELAY_MS)} мс после начала загрузки: быстрый ответ приходит без мелькания заглушек.`}
          >
            <StatusLine>{LOADING_STATUS}</StatusLine>
            <Variant label="delay = 0: сразу, как на витрине загрузки">
              <Skeleton count={1} />
            </Variant>
            <Variant
              label={`delay = ${String(SKELETON_DELAY_MS)}: появился через ${String(SKELETON_DELAY_MS)} мс после открытия витрины`}
            >
              <Skeleton count={1} delay={SKELETON_DELAY_MS} />
            </Variant>
          </Specimen>

          <Specimen
            id="base-match"
            title="MatchChips"
            note="Пометки «Совпало» под причиной: подписи признаков с положительным вкладом из contributions, без чисел, не больше четырёх. Статичные: без рамки, наведения и высоты 44 px. Галочка только рядом с текстом."
          >
            <Variant label="Задача и уточнения, P01">
              <MatchChips items={['тема', 'стадия', 'уровень', 'сфера']} />
            </Variant>
            <Variant label="Понятие из задачи, P02">
              <MatchChips items={['тема', 'суть задачи', 'стадия', 'уровень']} />
            </Variant>
            <Variant label="Смежный уровень, P01 и M03: вклад уровня есть, но причина говорит «на шаг глубже» — «уровень» не ставится">
              <MatchChips items={['тема', 'стадия']} />
            </Variant>
            <Variant label="История без задачи, P11">
              <MatchChips items={['продолжение', 'тема истории', 'похожие курсы']} />
            </Variant>
            <Variant label="Пустой список: компонент ничего не выводит, как у подбора по теме и стартовой подборки">
              <MatchChips items={[]} />
              <span className="note">Пометок нет</span>
            </Variant>
          </Specimen>

          <Specimen id="base-tag" title="Tag, TopBar" note="Screen и Layout — в разделе 4, «Экран целиком».">
            <div className="kit-row">
              <Tag>Демо-данные</Tag>
            </div>
            <div className="kit-frame">
              <TopBar brand="Учебная платформа" tag="Демо-данные" />
            </div>
            <div className="kit-frame">
              <TopBar brand="Учебная платформа" />
            </div>
          </Specimen>
        </div>
      </Section>

      <Section id="screen" title="4. Компоненты экрана">
        <Frames
          id="screen-full"
          title="Экран целиком: TaskForm, RefinementFields, DemoPanel, ResultList, RouteBlock"
          note="Screen > TopBar + Layout. Профиль P01, статус strong."
        >
          {() => <ScreenDemo />}
        </Frames>

        <Frames
          id="screen-loading"
          title="Загрузка"
          note="Поля заблокированы, кнопка «Подбираем…», строка состояния и три скелетона. На экране строка состояния появляется сразу, скелетоны — через 400 мс; на витрине они показаны сразу."
        >
          {() => <LoadingDemo />}
        </Frames>

        <Frames
          id="screen-stale"
          title="Загрузка до скелетонов: Stale"
          note="Первые 400 мс загрузки: строка состояния уже видна, прежняя выдача остаётся на месте, приглушена и неактивна — inert убирает её из обхода Tab и дерева доступности. Быстрый ответ сменяет её без мелькания заглушек и без схлопывания колонки, медленный — скелетонами."
        >
          {() => <StaleDemo />}
        </Frames>

        <Frames id="screen-cards" title="MaterialCard">
          {() => (
            <FrameBody>
              <p className="hint">Бесплатный материал, ссылка разрешена</p>
              <MaterialCard item={S.CARD_FREE} onComplete={noop} />
              <p className="hint">Платный курс: краткая польза и страница курса</p>
              <MaterialCard item={S.CARD_PAID_COURSE} onComplete={noop} />
              <p className="hint">Платный вебинар со ссылкой: страница материала</p>
              <MaterialCard item={S.CARD_PAID_MATERIAL} onComplete={noop} />
              <p className="hint">«По подписке»: страница материала (вымышленный пример)</p>
              <MaterialCard item={S.CARD_SUBSCRIPTION} onComplete={noop} />
              <p className="hint">Платный вебинар без разрешённой ссылки</p>
              <MaterialCard item={S.CARD_PAID_NO_LINK} onComplete={noop} />
              <p className="hint">Пометки истории «Вы уже открывали» и «В процессе»</p>
              <MaterialCard item={S.CARD_VIEWED} onComplete={noop} />
              <MaterialCard item={S.CARD_IN_PROGRESS} onComplete={noop} />
              <p className="hint">«Пройдено»: кнопки «Отметить изученным» нет</p>
              <MaterialCard item={S.CARD_COMPLETED} onComplete={noop} />
              <p className="hint">Смешанная выдача: бейдж темы</p>
              <MaterialCard item={S.CARD_TOPIC} showTopics onComplete={noop} />
              <p className="hint">Компактные карточки: сравнение и стартовая подборка</p>
              <MaterialCard item={S.CARD_COMPACT} compact onComplete={noop} />
              <MaterialCard item={S.CARD_COMPACT_FLAG} compact showTopics onComplete={noop} />
              <p className="hint">RouteBlock</p>
              <RouteBlock route={S.ROUTE} />
            </FrameBody>
          )}
        </Frames>

        <Frames id="screen-banners" title="StateBanner">
          {() => (
            <FrameBody>
              <StateBanner
                kind="clarification"
                clarification={S.WEAK_CLARIFICATION}
                topic={null}
                onChooseTopic={noop}
                onDismiss={noop}
              />
              <StateBanner kind="error" message={NETWORK_ERROR_TEXT} onRetry={noop} />
              <StateBanner kind="error" message="Каталог не загружен. Повторите запрос позже." onRetry={noop} />
            </FrameBody>
          )}
        </Frames>

        <Frames
          id="screen-weak"
          title="Слабое совпадение: StateBanner и ResultList"
          note="Статус weak: вопрос и темы в баннере, строка состояния, смешанная выдача с бейджами тем, «Показать ещё 5»."
        >
          {() => <WeakDemo />}
        </Frames>

        <Frames
          id="screen-empty"
          title="EmptyState: холодный старт"
          note="Статус cold: вопрос, темы, три карточки стартовой подборки и «Показать все 5». N — из total_candidates."
        >
          {() => <EmptyDemo response={S.COLD} />}
        </Frames>

        <Frames
          id="screen-none"
          title="EmptyState: пробел в каталоге"
          note="Статус none: сообщение о пробеле заголовком h2, темы каталога и стартовая подборка."
        >
          {() => <EmptyDemo response={S.NONE} />}
        </Frames>

        <Frames id="screen-intro" title="IntroPanel">
          {() => (
            <FrameBody>
              <IntroPanel onExample={noop} />
            </FrameBody>
          )}
        </Frames>

        <Frames
          id="screen-compare"
          title="CompareView"
          note="Ширина контейнера .screen: до 800 px — вкладки, от 800 px — две колонки. Профиль P02."
        >
          {() => <CompareDemo response={S.COMPARE} />}
        </Frames>

        <Frames
          id="screen-history-compare"
          title="CompareView: без задачи, подбор по истории"
          note="Пустая задача и история профиля, как у P11. Подбор по теме показывает стартовую подборку, персональный подбирает по истории со статусом weak: пометки «Совпало» называют продолжение, тему истории и похожие курсы. «Изменились позиции» не выводится."
        >
          {() => <CompareDemo response={S.COMPARE_HISTORY} />}
        </Frames>

        <Frames
          id="screen-starter-compare"
          title="CompareView: подбор по теме не нашёл тему"
          note="Задача «Какую CRM выбрать» без профиля. Подбор по теме вернул статус none: сообщение вместо подзаголовка и стартовая подборка с бейджами тем. Персональный подбор нашёл материалы о CRM. «Изменились позиции» не выводится. На узком экране открыта вкладка подбора по теме."
        >
          {() => <CompareDemo response={S.COMPARE_NO_TOPIC} initialTab="baseline" />}
        </Frames>
      </Section>
    </main>
  );
}
