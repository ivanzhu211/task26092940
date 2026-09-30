"""规模场景：7万条互不相关记录 + 3万条共享同一键的大组 + 1000次小组改键/删除。

该场景实际运行并报告耗时，整体必须在60秒内完成。
"""

import time

from dupreview import DuplicateReviewStore, Record

SINGLES = 70_000
SHARED = 30_000
SMALL_OPS = 1_000
TIME_LIMIT = 60.0


def test_large_scale_scenario():
    s = DuplicateReviewStore()
    t_start = time.perf_counter()

    # 阶段1：7万条互不相关的记录（各自唯一样品号）
    t0 = time.perf_counter()
    for i in range(SINGLES):
        s.upsert(Record(id=f"r{i}", item="铅含量",
                        sample_no=f"S{i}", raw_no=None, text="0.01"))
    t1 = time.perf_counter()

    # 阶段2：连续加入3万条共享同一键的记录，形成一个大组
    for i in range(SHARED):
        s.upsert(Record(id=f"big{i}", item="铅含量",
                        sample_no="SHARED", raw_no=None, text="0.02"))
    t2 = time.perf_counter()

    # 阶段3：读取大组，验证分组与放行状态
    insp = s.inspect("big0")
    assert len(insp.members) == SHARED
    assert insp.allowed is False  # 多成员组未确认不放行
    assert s.inspect(f"big{SHARED - 1}").token == insp.token
    assert s.confirm(insp.token) is True
    assert s.inspect("big0").allowed is True
    # 小组不受大组确认影响
    assert s.inspect("r0").members == ("r0",)
    assert s.inspect("r0").allowed is True
    t3 = time.perf_counter()

    # 阶段4：对小组连续执行1000次改键和删除
    # 偶数步：把 r{2k} 改键并入 r{2k+1} 形成小组；奇数步：删除该组成员
    for k in range(SMALL_OPS // 2):
        a, b = f"r{2 * k}", f"r{2 * k + 1}"
        s.upsert(Record(id=a, item="铅含量",
                        sample_no=f"S{2 * k + 1}", raw_no=None, text="0.03"))
        assert s.inspect(a).members == (a, b)
        s.remove(b)
        assert s.inspect(a).members == (a,)
        assert s.inspect(a).allowed is True
    t4 = time.perf_counter()

    # 验证：大组成员与确认状态未被小组操作影响
    final = s.inspect("big0")
    assert len(final.members) == SHARED
    assert final.token == insp.token
    assert final.allowed is True
    # 记录总数：7万 - 500删除 + 3万
    assert len(s._records) == SINGLES - SMALL_OPS // 2 + SHARED
    # 内部存储随记录数线性增长，不随重复对数量增长：
    # 全部索引桶成员数 == 每条记录的键数之和（此处每条记录恰好1个键）
    total_bucket_entries = sum(len(b) for b in s._index.values())
    assert total_bucket_entries == len(s._records)

    elapsed = t4 - t_start
    print(f"\n阶段1 插入{SINGLES}条独立记录: {t1 - t0:.2f}s")
    print(f"阶段2 插入{SHARED}条共享键记录: {t2 - t1:.2f}s")
    print(f"阶段3 读取并确认大组: {t3 - t2:.2f}s")
    print(f"阶段4 {SMALL_OPS}次小组改键/删除: {t4 - t3:.2f}s")
    print(f"总耗时: {elapsed:.2f}s（上限 {TIME_LIMIT:.0f}s）")
    assert elapsed < TIME_LIMIT
