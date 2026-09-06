import time
from pathlib import Path
from typing import Any

_EXHAUSTION_STATE: dict[str, float] = {}  # home -> reset_timestamp (unix epoch)


def mark_account_exhausted(home: str, until: float | None = None) -> None:
    """Mark an account home directory as exhausted/rate-limited until a timestamp."""
    if not home:
        return
    now = time.time()
    if until is None or until <= now:
        # Default cooldown: 30 minutes
        until = now + 1800.0
    _EXHAUSTION_STATE[home] = until
    try:
        marker_file = Path(home) / ".exhausted_until"
        marker_file.write_text(f"{until}\n")
    except Exception:
        pass


def is_account_exhausted(home: str) -> bool:
    """Check if an account is currently in cooldown/exhausted state."""
    if not home:
        return False
    now = time.time()
    until = _EXHAUSTION_STATE.get(home)
    if until is None:
        try:
            marker_file = Path(home) / ".exhausted_until"
            if marker_file.exists():
                until = float(marker_file.read_text().strip())
                _EXHAUSTION_STATE[home] = until
        except Exception:
            pass
    if until is not None:
        if now < until:
            return True
        else:
            # Cooldown has passed
            _EXHAUSTION_STATE.pop(home, None)
            try:
                (Path(home) / ".exhausted_until").unlink(missing_ok=True)
            except Exception:
                pass
    return False


def clear_account_exhaustion(home: str) -> None:
    """Clear exhaustion state for an account."""
    _EXHAUSTION_STATE.pop(home, None)
    try:
        (Path(home) / ".exhausted_until").unlink(missing_ok=True)
    except Exception:
        pass


def get_available_accounts(homes: tuple[str, ...]) -> list[str]:
    """Return all non-exhausted account homes."""
    return [h for h in homes if not is_account_exhausted(h)]


def are_all_accounts_exhausted(homes: tuple[str, ...]) -> bool:
    """Return True if all account homes in the pool are marked exhausted."""
    if not homes:
        return True
    return len(get_available_accounts(homes)) == 0


def select_account(
    homes: tuple[str, ...],
    *,
    marker: str,
    resume_token: str | None,
    session_pattern: str,
) -> str | None:
    if not homes:
        return None
    # 1. If resume token is present, check if its associated account home is healthy
    if resume_token:
        pattern = session_pattern.format(token=resume_token)
        for home in homes:
            if any(Path(home).glob(pattern)):
                if not is_account_exhausted(home):
                    return home
                # Resume account is exhausted; fall through to select a healthy account

    # 2. Pick next unexhausted account from candidates
    available = get_available_accounts(homes)
    candidates = available if available else list(homes)

    try:
        raw_idx = int(Path(marker).read_text().strip()) % len(homes)
        current_home = homes[raw_idx]
        if current_home in candidates:
            return current_home
    except (FileNotFoundError, OSError, ValueError):
        pass

    return candidates[0]


def rotate_account(
    homes: tuple[str, ...],
    *,
    marker: str,
    current: str | None,
    mark_exhausted: bool = False,
    exhausted_until: float | None = None,
) -> str | None:
    if len(homes) < 2:
        if mark_exhausted and current:
            mark_account_exhausted(current, until=exhausted_until)
        return current

    if mark_exhausted and current:
        mark_account_exhausted(current, until=exhausted_until)

    available = get_available_accounts(homes)
    candidates = available if available else list(homes)

    next_home = candidates[0]
    if current in homes:
        cur_idx = homes.index(current)
        for i in range(1, len(homes)):
            cand = homes[(cur_idx + i) % len(homes)]
            if cand in candidates:
                next_home = cand
                break

    try:
        next_idx = homes.index(next_home)
        path = Path(marker)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(f"{next_idx}\n")
        temporary.replace(path)
    except Exception:
        pass

    return next_home


def looks_exhausted(message: str | None) -> bool:
    text = (message or "").lower()
    return any(
        phrase in text
        for phrase in (
            "rate limit",
            "rate_limit",
            "usage limit",
            "quota",
            "resource_exhausted",
            "too many requests",
            "exceeded your current quota",
            "hit your usage limit",
            "upgrade to pro",
        )
    )


def get_all_account_statuses() -> dict[str, list[dict[str, Any]]]:
    """Inspect all configured accounts across engines and return their status, email, tier, and active state."""
    import json

    results: dict[str, list[dict[str, Any]]] = {}

    accounts_dir = Path("/var/lib/tunapi-accounts")

    # 1. Antigravity Accounts
    ag_homes = tuple(
        sorted(str(p) for p in accounts_dir.iterdir() if p.is_dir() and p.name.startswith("antigravity-"))
    ) if accounts_dir.is_dir() else ()
    ag_active = 0
    if ag_homes:
        try:
            ag_active = int(
                Path("/var/lib/tunapi-accounts/antigravity-active").read_text().strip()
            ) % len(ag_homes)
        except Exception:
            ag_active = 0

    ag_list: list[dict[str, Any]] = []
    for idx, home in enumerate(ag_homes):
        p = Path(home)
        name = p.name
        is_active = idx == ag_active
        exhausted = is_account_exhausted(home)
        email = ""
        g_acc = p / ".gemini" / "google_accounts.json"
        if g_acc.exists():
            try:
                email = json.loads(g_acc.read_text()).get("active", "")
            except Exception:
                pass

        if exhausted:
            st = "Exhausted / Rate Limited (Cooldown)"
        elif is_active:
            st = "Active / Online"
        else:
            st = "Standby (Ready)"

        ag_list.append(
            {
                "name": name,
                "email": email or name.replace("antigravity-", ""),
                "is_active": is_active,
                "is_exhausted": exhausted,
                "status": st,
            }
        )
    if ag_list:
        results["antigravity"] = ag_list

    # 2. Claude Accounts
    cl_homes = tuple(
        sorted(str(p) for p in accounts_dir.iterdir() if p.is_dir() and p.name.startswith("claude-"))
    ) if accounts_dir.is_dir() else ()
    cl_active = 0
    if cl_homes:
        try:
            cl_active = int(
                Path("/var/lib/tunapi-accounts/claude-active").read_text().strip()
            ) % len(cl_homes)
        except Exception:
            cl_active = 0

    cl_list: list[dict[str, Any]] = []
    for idx, home in enumerate(cl_homes):
        p = Path(home)
        name = p.name
        is_active = idx == cl_active
        exhausted = is_account_exhausted(home)
        cl_json = p / ".claude.json"
        email = ""
        tier = "Claude Pro"
        if cl_json.exists():
            try:
                data = json.loads(cl_json.read_text())
                oauth = data.get("oauthAccount", {})
                email = oauth.get("emailAddress", "")
                org_type = oauth.get("organizationType", "claude_pro")
                tier = org_type.replace("_", " ").title()
            except Exception:
                pass

        if exhausted:
            st = "Exhausted / Rate Limited (Cooldown)"
        elif is_active:
            st = "Active / Online"
        else:
            st = "Standby (Ready)"

        cl_list.append(
            {
                "name": name,
                "email": email or name.replace("claude-", ""),
                "tier": tier,
                "is_active": is_active,
                "is_exhausted": exhausted,
                "status": st,
            }
        )
    if cl_list:
        results["claude"] = cl_list

    return results
