from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evaluation"))

from next_course import Enrollment, build_cases, evaluate, paired_interval


def date(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


AVAILABLE = frozenset({"source", "target", "other", "already_started"})


def test_cases_skip_ties_and_exclude_started_courses():
    history = [
        Enrollment("user", "source", date(1), date(1), date(4)),
        Enrollment("user", "already_started", date(2), date(2)),
        Enrollment("user", "other", date(3), date(4)),
        Enrollment("user", "target", date(2), date(5)),
    ]
    case, = build_cases(history, AVAILABLE)
    assert case.at == date(4)
    assert case.target == "target" and case.candidates == {"target"}
    history[2] = Enrollment("user", "other", date(3), date(5))
    assert build_cases(history, AVAILABLE) == []


def test_pair_support_excludes_test_user_duplicates_and_future_interactions():
    records = [
        Enrollment("test", "source", date(1), date(1), date(4)),
        Enrollment("test", "target", date(1), date(5)),
    ]
    for i in range(4):
        records.extend([Enrollment(str(i), "source", date(1)), Enrollment(str(i), "target", date(1))])
    records.extend([
        Enrollment("0", "target", date(2)),  # повтор пользователя
        Enrollment("same-day", "source", date(1)),
        Enrollment("same-day", "target", date(4)),  # ровно на границе среза
        Enrollment("future", "source", date(1)),
        Enrollment("future", "target", date(6)),
    ])
    for i in range(6):
        records.append(Enrollment(f"popular-{i}", "other", date(1)))
    outcome = evaluate(records, AVAILABLE)
    assert outcome["cases"] == 1
    assert outcome["methods"]["coenrollment"]["shown"] == 0
    assert outcome["methods"]["popularity"]["hits_at_1"] == 0
    assert outcome["passes_gate"] is False

    records.extend([Enrollment("extra", "source", date(1)), Enrollment("extra", "target", date(2))])
    outcome = evaluate(records, AVAILABLE)
    assert outcome["methods"]["coenrollment"]["hits_at_1"] == 1
    assert outcome["hit_at_1_delta"] == 1
    assert outcome["passes_gate"] is False


def test_paired_interval_retains_uncertainty_without_discordant_pairs():
    lower, upper = paired_interval([0] * 12)
    assert lower == -upper and upper > 0
    assert paired_interval([1] * 30)[0] > 0
