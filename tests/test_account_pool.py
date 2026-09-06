import time
from pathlib import Path
from tunapi.account_pool import (
    are_all_accounts_exhausted,
    clear_account_exhaustion,
    get_available_accounts,
    is_account_exhausted,
    looks_exhausted,
    mark_account_exhausted,
    rotate_account,
    select_account,
)


def test_looks_exhausted() -> None:
    assert looks_exhausted("You've hit your usage limit. Upgrade to Pro")
    assert looks_exhausted("Rate limit exceeded")
    assert looks_exhausted("ResourceExhausted: 429 Too Many Requests")
    assert looks_exhausted("Quota exceeded for quota metric")
    assert not looks_exhausted("SyntaxError: invalid syntax")
    assert not looks_exhausted(None)


def test_account_exhaustion_state(tmp_path: Path) -> None:
    acc1 = str(tmp_path / "acc1")
    acc2 = str(tmp_path / "acc2")
    Path(acc1).mkdir()
    Path(acc2).mkdir()

    clear_account_exhaustion(acc1)
    clear_account_exhaustion(acc2)

    assert not is_account_exhausted(acc1)
    assert not is_account_exhausted(acc2)

    # Mark acc1 exhausted
    mark_account_exhausted(acc1, until=time.time() + 60.0)
    assert is_account_exhausted(acc1)
    assert not is_account_exhausted(acc2)

    assert get_available_accounts((acc1, acc2)) == [acc2]
    assert not are_all_accounts_exhausted((acc1, acc2))

    # Mark acc2 exhausted
    mark_account_exhausted(acc2, until=time.time() + 60.0)
    assert are_all_accounts_exhausted((acc1, acc2))

    # Clear exhaustion
    clear_account_exhaustion(acc1)
    clear_account_exhaustion(acc2)
    assert not are_all_accounts_exhausted((acc1, acc2))


def test_select_account_skips_exhausted(tmp_path: Path) -> None:
    acc1 = str(tmp_path / "acc1")
    acc2 = str(tmp_path / "acc2")
    Path(acc1).mkdir()
    Path(acc2).mkdir()
    marker = str(tmp_path / "active")

    clear_account_exhaustion(acc1)
    clear_account_exhaustion(acc2)

    # Initially select acc1
    selected = select_account(
        (acc1, acc2),
        marker=marker,
        resume_token=None,
        session_pattern="*.json",
    )
    assert selected == acc1

    # When acc1 is exhausted, select_account picks acc2
    mark_account_exhausted(acc1, until=time.time() + 60.0)
    selected = select_account(
        (acc1, acc2),
        marker=marker,
        resume_token=None,
        session_pattern="*.json",
    )
    assert selected == acc2


def test_rotate_account_with_exhaustion(tmp_path: Path) -> None:
    acc1 = str(tmp_path / "acc1")
    acc2 = str(tmp_path / "acc2")
    Path(acc1).mkdir()
    Path(acc2).mkdir()
    marker = str(tmp_path / "active")

    clear_account_exhaustion(acc1)
    clear_account_exhaustion(acc2)

    next_acc = rotate_account(
        (acc1, acc2),
        marker=marker,
        current=acc1,
        mark_exhausted=True,
    )
    assert next_acc == acc2
    assert is_account_exhausted(acc1)
    assert not is_account_exhausted(acc2)
