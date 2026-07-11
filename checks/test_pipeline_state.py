from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline_state import (
    INTERNAL_TO_USER_STEP,
    USER_TO_INTERNAL_STEPS,
    begin_step,
    complete_step,
    current_step_after_completion,
    mark_retry_needed,
    validate_statuses,
)


def _statuses(value: str = "pending") -> dict[str, str]:
    return {str(step): value for step in range(1, 9)}


def test_visible_and_internal_step_mapping_is_complete() -> None:
    assert USER_TO_INTERNAL_STEPS == {
        1: (1,),
        2: (2,),
        3: (3, 4),
        4: (5,),
        5: (6, 7),
        6: (8,),
    }
    assert set(INTERNAL_TO_USER_STEP) == set(range(1, 9))


def test_begin_step_does_not_mutate_input() -> None:
    original = _statuses("completed")
    result = begin_step(original, 6)
    assert original == _statuses("completed")
    assert result["6"] == "in_progress"
    assert result["7"] == "pending_reconfirmation"
    assert result["8"] == "pending_reconfirmation"


def test_complete_step_resets_existing_stale_downstream() -> None:
    original = _statuses()
    original.update({"2": "in_progress", "3": "completed", "4": "pending_reconfirmation", "5": "in_progress"})
    result = complete_step(original, 2)
    assert result["2"] == "completed"
    assert result["3"] == "pending_reconfirmation"
    assert result["4"] == "pending"
    assert result["5"] == "pending"


def test_retry_marks_target_stale_and_downstream_pending() -> None:
    original = _statuses("completed")
    result = mark_retry_needed(original, 7)
    assert result["6"] == "completed"
    assert result["7"] == "pending_reconfirmation"
    assert result["8"] == "pending"


def test_invalid_steps_and_states_are_rejected() -> None:
    with pytest.raises(ValueError):
        begin_step(_statuses(), 0)
    with pytest.raises(ValueError):
        complete_step(_statuses(), 9)
    invalid = _statuses()
    invalid["4"] = "done"
    with pytest.raises(ValueError):
        validate_statuses(invalid)


def test_current_step_never_moves_back_on_completion() -> None:
    assert current_step_after_completion(None, 3) == 3
    assert current_step_after_completion(6, 2) == 6
    assert current_step_after_completion(4, 7) == 7


if __name__ == "__main__":
    test_visible_and_internal_step_mapping_is_complete()
    test_begin_step_does_not_mutate_input()
    test_complete_step_resets_existing_stale_downstream()
    test_retry_marks_target_stale_and_downstream_pending()
    test_invalid_steps_and_states_are_rejected()
    test_current_step_never_moves_back_on_completion()
    print("pipeline state checks passed")
