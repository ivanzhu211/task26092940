"""大规模性能场景测试：7 万条互不相关记录 + 3 万条共享同一键的记录。

真实构造全部数据并执行操作，整个场景必须在 60 秒内完成。
"""

import time

from dupcheck import DuplicateReviewStore, Record

SMALL_COUNT = 70_000
LARGE_COUNT = 30_000
CHURN_OPS = 1_000
TIME_BUDGET_SECONDS = 60.0


def test_large_scale_scenario() -> None:
    store = DuplicateReviewStore()
    started = time.perf_counter()

    # 7 万条互不相关的记录：各自成组，单成员组直接放行。
    for i in range(SMALL_COUNT):
        store.upsert(Record(f"small-{i}", "item1", sample_no=f"S-{i}"))
    t_small = time.perf_counter() - started

    inspection = store.inspect("small-0")
    assert inspection.members == frozenset({"small-0"})
    assert inspection.releasable is True

    # 连续加入 3 万条共享同一键的记录，形成一个大组。
    t0 = time.perf_counter()
    for i in range(LARGE_COUNT):
        store.upsert(Record(f"large-{i}", "item1", sample_no="SHARED"))
    t_large = time.perf_counter() - t0

    # 读取大组：成员齐全、未确认前不放行。
    t0 = time.perf_counter()
    big = store.inspect("large-0")
    t_inspect = time.perf_counter() - t0
    assert len(big.members) == LARGE_COUNT
    assert "large-0" in big.members
    assert f"large-{LARGE_COUNT - 1}" in big.members
    assert big.releasable is False
    # 大组确认后放行，且不影响小组。
    assert store.confirm(big.token) is True
    assert store.inspect(f"large-{LARGE_COUNT - 1}").releasable is True
    assert store.inspect("small-1").releasable is True

    # 对小组连续执行 1000 次改键和删除。
    t0 = time.perf_counter()
    for i in range(CHURN_OPS):
        rid = f"small-{i}"
        if i % 2 == 0:
            # 改键：换成新的唯一键（完整替换记录）。
            store.upsert(Record(rid, "item1", sample_no=f"S-{i}-v2", text="rev2"))
        else:
            store.remove(rid)
    t_churn = time.perf_counter() - t0

    # 验证改键/删除后的小组状态。
    assert store.inspect("small-0").members == frozenset({"small-0"})
    assert store.inspect("small-0").releasable is True
    assert store.remove("small-1") is False  # 已在循环中删除
    assert store.inspect("small-2").members == frozenset({"small-2"})
    # 大组不受小组变更影响，确认仍然有效。
    assert store.inspect("large-0").releasable is True
    assert len(store.inspect("large-0").members) == LARGE_COUNT

    total = time.perf_counter() - started
    print(
        f"\n性能场景耗时: 7万小组 upsert={t_small:.2f}s, "
        f"3万大组 upsert={t_large:.2f}s, 读取大组={t_inspect:.3f}s, "
        f"1000次改键/删除={t_churn:.3f}s, 总计={total:.2f}s"
    )
    assert total < TIME_BUDGET_SECONDS
