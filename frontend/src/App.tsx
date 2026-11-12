import { useEffect, useRef, useState } from 'react';
import type { TopicCode } from './api/types';
import { CatalogTopics } from './components/CatalogTopics';
import { DemoPanel } from './components/DemoPanel';
import { IntroPanel } from './components/IntroPanel';
import { RecommendationPane } from './components/RecommendationPane';
import { TaskForm } from './components/TaskForm';
import { Screen, TopBar } from './kit';
import { DEFAULT_MAX_TASK_LENGTH, useMeta } from './state/useMeta';
import { useRecommend, type Section } from './state/useRecommend';

function currentSection(): Section {
  return window.location.hash === '#catalog' ? 'catalog' : 'recommend';
}

export function App() {
  const [section, setSection] = useState(currentSection);
  const [catalogTopic, setCatalogTopic] = useState<TopicCode | null>(null);
  const { meta, profiles, failed, reload } = useMeta();
  const session = useRecommend(section);
  const { recommendation, catalog } = session;
  const topics = meta?.topics ?? [];
  const sectionHeading = useRef<HTMLHeadingElement>(null);
  const previousSection = useRef(section);

  useEffect(() => {
    const update = () => setSection(currentSection());
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);

  useEffect(() => {
    if (previousSection.current !== section) {
      sectionHeading.current?.focus();
      previousSection.current = section;
    }
  }, [section]);

  return (
    <Screen>
      <TopBar
        brand="Учебная платформа"
        navigation={
          <nav className="topbar__nav" aria-label="Разделы">
            <a href="#recommend" aria-current={section === 'recommend' ? 'page' : undefined}>Подбор</a>
            <a href="#catalog" aria-current={section === 'catalog' ? 'page' : undefined}>Каталог</a>
          </nav>
        }
      />
      <main>
        <RecommendationPane
          active={section === 'recommend'}
          result={recommendation}
          topics={topics}
          topic={session.topic}
          chooseTopic={recommendation.chooseTopic}
          intro={<IntroPanel />}
          aside={(submit, resetView) => (
            <>
              <TaskForm
                headingRef={sectionHeading}
                meta={meta}
                metaFailed={failed}
                values={session.form}
                maxLength={meta?.max_task_length ?? DEFAULT_MAX_TASK_LENGTH}
                error={recommendation.state.fieldError}
                loading={recommendation.state.loading}
                onTaskChange={session.setTask}
                onRefinementsChange={session.setRefinements}
                onSubmit={() => {
                  if (failed) reload();
                  submit(recommendation.submit);
                }}
                onReset={() => {
                  resetView();
                  setCatalogTopic(null);
                  session.reset();
                }}
              />
              {profiles ? (
                <DemoPanel
                  profiles={profiles}
                  profileId={session.profileId}
                  onSelectProfile={(id) => {
                    resetView();
                    setCatalogTopic(null);
                    session.selectProfile(profiles.find((profile) => profile.id === id) ?? null);
                  }}
                  compare={session.compare}
                  onCompareChange={session.setCompare}
                  disabled={recommendation.state.loading}
                />
              ) : null}
            </>
          )}
        />
        <RecommendationPane
          active={section === 'catalog'}
          result={catalog}
          topics={topics}
          catalog
          aside={(submit) => (
            <CatalogTopics
              headingRef={sectionHeading}
              topics={topics}
              loaded={meta !== null}
              failed={failed}
              reload={reload}
              value={catalogTopic}
              current={catalog.state.lastCall?.body.topic ?? null}
              onChange={setCatalogTopic}
              onShow={(topic) => {
                setCatalogTopic(topic);
                submit(() => catalog.browseTopic(topic));
              }}
              disabled={catalog.state.loading}
            />
          )}
        />
      </main>
    </Screen>
  );
}
