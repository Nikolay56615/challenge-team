import { lazy, Suspense, useState } from 'react';
import { FeedScreen } from './components/FeedScreen';
import { Banner, Button, Checkbox, Screen, TabPanel, Tabs, TopBar, type TabItem } from './kit';
import { useMeta } from './state/useMeta';

// Подбор по задаче — дополнительная функция: его код загружается, когда путь открыт
const TaskScreen = lazy(() => import('./TaskScreen').then((module) => ({ default: module.TaskScreen })));

/** Путь экрана: лента клиента с историей, лента нового клиента или подбор по тексту задачи */
type View = 'history' | 'new' | 'task';

const VIEW_TABS: readonly (TabItem & { view: View })[] = [
  { id: 'view-history', view: 'history', label: 'Клиент с\u00A0историей' },
  { id: 'view-new', view: 'new', label: 'Новый клиент' },
  { id: 'view-task', view: 'task', label: 'Подбор по\u00A0задаче' },
];

/** Путь из адреса: `?view=history`, `?view=new` или `?view=task`; иначе выбирается по наличию клиентов с историей */
function viewFromLocation(): View | null {
  const value = new URLSearchParams(window.location.search).get('view');
  return VIEW_TABS.find((tab) => tab.view === value)?.view ?? null;
}

/**
 * Вход — развилка (docs/plan.md, 13.9). Первой открывается лента клиента с историей: рекомендации строятся
 * по профилю, без ввода текста. Рядом — лента нового клиента и подбор по задаче как дополнительная функция.
 */
export function App() {
  const metaState = useMeta();
  const [chosen, setChosen] = useState<View | null>(viewFromLocation);
  // Вид клиента показывает ленту так, как её увидел бы сам клиент: без оценок, расчёта и панелей
  const [clientView, setClientView] = useState(false);
  const clients = metaState.users;
  const withClients = (clients?.total ?? 0) > 0;
  // Пока справочники и клиенты не загружены, путь не выбран: лента не мигает экраном подбора
  const ready = metaState.meta !== null || metaState.failed;
  const tabs = withClients ? VIEW_TABS : VIEW_TABS.filter((tab) => tab.view !== 'history');
  const fallback: View = withClients ? 'history' : 'new';
  const view = tabs.some((tab) => tab.view === chosen) && chosen ? chosen : fallback;

  return (
    <Screen>
      <TopBar brand="Учебная платформа" />
      {ready ? (
        <>
          <div className="mode-switch">
            <Tabs
              ariaLabel="Для кого показать рекомендации"
              tabs={tabs}
              selected={`view-${view}`}
              // В виде клиента вкладки скрыты: на экране остаётся то, что увидел бы клиент, и флажок возврата
              hidden={clientView && view !== 'task'}
              onSelect={(id) => {
                setChosen(tabs.find((tab) => tab.id === id)?.view ?? fallback);
              }}
            />
            {view === 'task' ? null : (
              <Checkbox
                checked={clientView}
                onChange={setClientView}
                label={'Вид клиента: без оценок и\u00A0расчёта'}
              />
            )}
          </div>
          {metaState.usersFailed && view !== 'task' ? (
            <div className="mode-switch">
              <Banner
                tone="error"
                title="Список клиентов не загрузился"
                actions={
                  <Button variant="secondary" onClick={metaState.reload}>
                    Повторить
                  </Button>
                }
              >
                Сервис не ответил. Путь «Клиент с&nbsp;историей» появится после повтора.
              </Banner>
            </div>
          ) : null}
          {tabs.map((tab) => (
            <TabPanel key={tab.id} tabId={tab.id} hidden={tab.view !== view}>
              {tab.view !== view ? null : view === 'task' ? (
                <Suspense fallback={null}>
                  <TaskScreen metaState={metaState} />
                </Suspense>
              ) : (
                <FeedScreen
                  key={view}
                  mode={view}
                  clients={clients?.users ?? []}
                  clientsTotal={clients?.total ?? 0}
                  meta={metaState.meta}
                  audience={clientView ? 'client' : 'product'}
                  onOpenTask={() => {
                    setChosen('task');
                  }}
                />
              )}
            </TabPanel>
          ))}
        </>
      ) : null}
    </Screen>
  );
}
