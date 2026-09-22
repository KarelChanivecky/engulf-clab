from engulf_clab_license_pool import AllocationRequest, LicensePoolSelector, LicenseStrategy, PoolState


def test_selector_preserves_round_robin_strategy() -> None:
    selector = LicensePoolSelector()
    state = PoolState.empty()
    files = ("/licenses/a.lic", "/licenses/b.lic")

    first = selector.select(
        state,
        files=files,
        request=AllocationRequest("/labs/one:router"),
        strategy=LicenseStrategy.ROUND_ROBIN,
    )
    second = selector.select(
        state,
        files=files,
        request=AllocationRequest("/labs/two:router"),
        strategy=LicenseStrategy.ROUND_ROBIN,
    )

    assert first is not None and first.path == files[0] and first.created
    assert second is not None and second.path == files[1] and second.created


def test_selector_reuses_active_claim_and_honors_clamp() -> None:
    selector = LicensePoolSelector()
    state = PoolState.empty()
    files = ("/licenses/a.lic", "/licenses/b.lic")

    selected = selector.select(
        state,
        files=files,
        request=AllocationRequest("/labs/one:router", clamp="/licenses/b.lic"),
        strategy=LicenseStrategy.LEAST_RECENTLY_USED,
    )
    retry = selector.select(
        state,
        files=files,
        request=AllocationRequest("/labs/one:router"),
        strategy=LicenseStrategy.STICKY,
    )

    assert selected is not None and selected.path == files[1]
    assert retry is not None and retry.path == files[1] and not retry.created
