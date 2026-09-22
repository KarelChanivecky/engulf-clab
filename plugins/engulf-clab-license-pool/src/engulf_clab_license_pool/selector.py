from __future__ import annotations

from collections.abc import Sequence

from engulf_clab_license_pool_lib import (
    AllocationRequest,
    AllocationResult,
    LicensePoolError,
    LicenseStrategy,
    PoolState,
    PoolSelector,
)


class LicensePoolSelector(PoolSelector):
    """Concrete selector implementing the standard license strategies."""

    def select(
        self,
        state: PoolState,
        *,
        files: Sequence[str],
        request: AllocationRequest,
        strategy: LicenseStrategy | str,
    ) -> AllocationResult | None:
        strategy = _coerce_strategy(strategy)
        candidates = list(files)
        existing = next(
            (path for path, owner in state.allocations.items() if owner == request.claim),
            None,
        )
        if existing in candidates:
            _record_use(state, existing)
            return AllocationResult(existing, False)
        free = [path for path in candidates if path not in state.allocations]
        if request.clamp:
            target = request.clamp if request.clamp.startswith("/") else next(
                (path for path in candidates if path.rsplit("/", 1)[-1] == request.clamp),
                request.clamp,
            )
            if target not in free:
                return None
            choice = target
            if choice not in state.clamped:
                state.clamped.append(choice)
        else:
            choice = _select_available(state, candidates, free, request.claim, strategy)
            if choice is None:
                return None
        state.allocations[choice] = request.claim
        state.history[choice] = request.claim
        _record_use(state, choice)
        return AllocationResult(choice, True)


def _coerce_strategy(value: LicenseStrategy | str) -> LicenseStrategy:
    try:
        return LicenseStrategy(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(strategy.value for strategy in LicenseStrategy)
        raise LicensePoolError(f"license pool strategy must be one of: {choices}") from error


def _select_available(
    state: PoolState,
    files: list[str],
    free: list[str],
    claim: str,
    strategy: LicenseStrategy,
) -> str | None:
    if strategy is LicenseStrategy.STICKY:
        preferred = [
            path for path in free
            if state.history.get(path) == claim and path not in state.clamped
        ]
        never = [path for path in free if path not in state.history]
        normal = [path for path in free if path not in state.clamped]
        for candidates in (preferred, never, normal, free):
            if candidates:
                return candidates[0]
        return None
    available = [path for path in free if path not in state.clamped] or free
    if not available:
        return None
    if strategy is LicenseStrategy.LEAST_RECENTLY_USED:
        return min(available, key=lambda path: (state.last_used.get(path, -1), path))
    available_set = set(available)
    start = state.round_robin_index % len(files)
    for offset in range(len(files)):
        index = (start + offset) % len(files)
        if files[index] in available_set:
            state.round_robin_index = (index + 1) % len(files)
            return files[index]
    return None


def _record_use(state: PoolState, path: str) -> None:
    state.usage_sequence += 1
    state.last_used[path] = state.usage_sequence


selector = LicensePoolSelector()
