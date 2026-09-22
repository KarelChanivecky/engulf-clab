from pathlib import Path

from engulf_clab_license_pool_lib import (
    LicensePoolManager,
    PoolManagerRequest,
    PoolManagerResult,
    PoolState,
    run_pool_managers,
)


class MemoryState:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def exists(self, filename: str) -> bool:
        return filename in self.values

    def read_text(self, filename: str) -> str:
        return self.values[filename]

    def write_text(self, filename: str, value: str) -> None:
        self.values[filename] = value

    def transaction(self):
        from contextlib import nullcontext

        return nullcontext(self)


def test_manager_exposes_registered_pools_without_selector_policy(tmp_path) -> None:
    state = MemoryState()
    manager = LicensePoolManager(state)
    pool = tmp_path / "enterprise"
    pool.mkdir()

    result = manager.manage(manager, PoolManagerRequest(pool, "linux"))
    assert result.changed
    assert manager.registered_pools()[0].path == str(pool)
    assert manager.registered_pools()[0].kind == "linux"
    assert manager.remove(pool)
    assert not manager.registered_pools()


def test_manager_chain_preempts_later_manager() -> None:
    calls: list[str] = []

    class First:
        def manage(self, store, request):
            del store, request
            calls.append("first")
            return PoolManagerResult(preempt=True, changed=True)

    class Second:
        def manage(self, store, request):
            del store, request
            calls.append("second")
            return PoolManagerResult()

    result = run_pool_managers(
        (First(), Second()),
        object(),
        PoolManagerRequest(Path("/tmp"), "linux"),
    )

    assert calls == ["first"]
    assert result.preempt and result.changed
