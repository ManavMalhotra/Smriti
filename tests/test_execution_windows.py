from __future__ import annotations

import json
from itertools import islice

import pytest

from smriti.stage import execution_windows

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("pages", [1, 20, 21, 39, 40, 41, 1001])
def test_ranges_are_ordered_complete_global_and_nonoverlapping(pages):
    windows = list(execution_windows((("job", pages),)))
    ranges = [member for window in windows for member in window["members"]]
    assert [page for item in ranges for page in range(item["start"], item["end"] + 1)] == list(range(1, pages + 1))
    assert all(item["end"] - item["start"] + 1 <= 20 for item in ranges)
    assert all(len(json.dumps(window)) < 1024 for window in windows)
    assert windows[-1]["next_member"] == 1 and windows[-1]["next_page"] == 1


@pytest.mark.parametrize("counts, expected", [
    ([20, 1], [[("a", 1, 20)], [("b", 1, 1)]]),
    ([15, 15], [[("a", 1, 15)], [("b", 1, 15)]]),
    ([14, 12], [[("a", 1, 14)], [("b", 1, 12)]]),
    ([3, 4], [[("a", 1, 3), ("b", 1, 4)]]),
    ([39, 1], [[("a", 1, 20)], [("a", 21, 39)], [("b", 1, 1)]]),
    ([1, 39, 1], [[("a", 1, 1)], [("b", 1, 20)], [("b", 21, 39)], [("c", 1, 1)]]),
])
def test_short_packing_and_long_isolation_preserve_fifo(counts, expected):
    windows = execution_windows(tuple(zip("abc", counts)))
    actual = [[(member["job_id"], member["start"], member["end"]) for member in window["members"]] for window in windows]
    assert actual == expected


def test_huge_document_never_materializes_future_windows_and_cursor_resumes_directly():
    members = (("a", 20_000_001), ("b", 1))
    windows = list(islice(execution_windows(members), 2))
    assert windows[-1]["next_page"] == 41
    resumed = next(execution_windows(members, member_position=0, next_page=2_000_001))
    assert resumed["members"] == [{"job_id": "a", "start": 2_000_001, "end": 2_000_020}]
    assert len(json.dumps(resumed)) < 256


def test_rejected_members_leave_holes_without_admitting_new_jobs():
    windows = list(execution_windows((("a", 1), ("rejected", None), ("b", 2))))
    assert [member["job_id"] for member in windows[0]["members"]] == ["a", "b"]
    assert list(execution_windows((("rejected", None),))) == []


@pytest.mark.parametrize("members, kwargs", [
    ([], {}), ([(str(index), 1) for index in range(11)], {}),
    ([("a", True)], {}), ([("a", 0)], {}),
    ([("a", 1)], {"cap": 21}), ([("a", 1)], {"cap": True}),
    ([("a", 2)], {"next_page": 2}), ([("a", 39)], {"next_page": 40}),
])
def test_bad_members_or_cursors_fail_before_execution(members, kwargs):
    with pytest.raises(ValueError):
        list(execution_windows(members, **kwargs))
