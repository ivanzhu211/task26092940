"""桥接记录连接两个已确认组，随后删除桥接记录恢复两个组。"""

from dupreview import DuplicateReviewStore, Record


def rec(id, item="铅含量", sample=None, raw=None, text="0.01"):
    return Record(id=id, item=item, sample_no=sample, raw_no=raw, text=text)


def test_bridge_merge_then_split_requires_reconfirmation():
    s = DuplicateReviewStore()
    # 组A：a1-a2-a3 共享样品号SA；组B：b1-b2 共享原始记录号RB
    for rid in ("a1", "a2", "a3"):
        s.upsert(rec(rid, sample="SA"))
    for rid in ("b1", "b2"):
        s.upsert(rec(rid, raw="RB"))
    ta = s.inspect("a1").token
    tb = s.inspect("b1").token
    assert s.confirm(ta) and s.confirm(tb)
    assert s.inspect("a2").allowed and s.inspect("b2").allowed

    # 桥接记录 x 同时连接两组（样品号SA + 原始记录号RB）
    s.upsert(rec("x", sample="SA", raw="RB"))
    merged = s.inspect("a1")
    assert merged.members == ("a1", "a2", "a3", "b1", "b2", "x")
    assert len(merged.members) == len(set(merged.members))  # 无重复
    # 合组不继承任一旧组确认，旧token全部失效
    assert merged.allowed is False
    assert s.confirm(ta) is False
    assert s.confirm(tb) is False
    # 合组后所有成员共享同一token
    assert s.inspect("b2").token == merged.token
    assert s.inspect("x").token == merged.token

    # 确认合组后可放行
    assert s.confirm(merged.token) is True
    assert s.inspect("b1").allowed is True

    # 删除桥接记录，恢复两个组；拆组后的各组不继承确认
    s.remove("x")
    group_a = s.inspect("a1")
    group_b = s.inspect("b1")
    assert group_a.members == ("a1", "a2", "a3")
    assert group_b.members == ("b1", "b2")
    assert group_a.token != group_b.token
    assert group_a.allowed is False
    assert group_b.allowed is False
    # 合组token与最早的旧token都不能复活
    assert s.confirm(merged.token) is False
    assert s.confirm(ta) is False
    assert s.confirm(tb) is False

    # 再次拆组后必须重新确认才能放行
    assert s.confirm(group_a.token) is True
    assert s.confirm(group_b.token) is True
    assert s.inspect("a3").allowed is True
    assert s.inspect("b2").allowed is True


def test_bridge_via_upsert_key_change():
    """桥接也可以通过改键形成与拆除。"""
    s = DuplicateReviewStore()
    s.upsert(rec("a1", sample="SA"))
    s.upsert(rec("a2", sample="SA"))
    s.upsert(rec("b1", raw="RB"))
    s.upsert(rec("b2", raw="RB"))
    s.upsert(rec("x", sample="SX"))  # 独立单成员
    assert s.confirm(s.inspect("a1").token)
    assert s.confirm(s.inspect("b1").token)

    # x 改键成为桥
    s.upsert(rec("x", sample="SA", raw="RB"))
    assert s.inspect("x").members == ("a1", "a2", "b1", "b2", "x")
    assert s.inspect("a1").allowed is False

    # x 再改键离开，两个组恢复但需重新确认
    s.upsert(rec("x", sample="SX"))
    assert s.inspect("x").members == ("x",)
    assert s.inspect("a1").members == ("a1", "a2")
    assert s.inspect("b1").members == ("b1", "b2")
    assert s.inspect("a1").allowed is False
    assert s.inspect("b1").allowed is False
