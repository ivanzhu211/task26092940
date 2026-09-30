"""token 与确认状态测试：放行规则、失效规则、合组/拆组不继承确认。"""

from dupcheck import DuplicateReviewStore, Record


def make_store() -> DuplicateReviewStore:
    return DuplicateReviewStore()


def test_single_member_group_releasable_without_confirm() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    inspection = store.inspect("A")
    assert inspection.members == frozenset({"A"})
    assert inspection.releasable is True


def test_multi_member_group_requires_confirm() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1"))
    assert store.inspect("A").releasable is False
    token = store.inspect("A").token
    assert store.confirm(token) is True
    assert store.inspect("A").releasable is True
    assert store.inspect("B").releasable is True


def test_group_members_share_token_and_status() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1"))
    store.upsert(Record("C", "item1", sample_no="S1"))
    tokens = {store.inspect(r).token for r in "ABC"}
    assert len(tokens) == 1
    store.confirm(tokens.pop())
    assert all(store.inspect(r).releasable for r in "ABC")


def test_unknown_token_fails() -> None:
    store = make_store()
    assert store.confirm("no-such-token") is False


def test_text_only_revision_invalidates_token() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1", text="0.1"))
    store.upsert(Record("B", "item1", sample_no="S1", text="0.2"))
    token = store.inspect("A").token
    assert store.confirm(token) is True
    assert store.inspect("A").releasable is True
    # 仅修改结果文本，也必须撤销确认并永久失效旧 token。
    store.upsert(Record("A", "item1", sample_no="S1", text="0.9"))
    assert store.inspect("A").releasable is False
    assert store.confirm(token) is False
    # 新 token 确认后恢复放行。
    assert store.confirm(store.inspect("A").token) is True
    assert store.inspect("A").releasable is True


def test_temp_member_add_remove_does_not_revive_token() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1"))
    token = store.inspect("A").token
    assert store.confirm(token) is True
    # 加入再移除临时成员，恢复原成员集合，旧 token 不能复活。
    store.upsert(Record("TMP", "item1", sample_no="S1"))
    store.remove("TMP")
    assert store.inspect("A").members == frozenset({"A", "B"})
    assert store.confirm(token) is False
    assert store.inspect("A").releasable is False


def test_unaffected_group_keeps_confirmation() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1"))
    store.upsert(Record("X", "item1", sample_no="S9"))
    store.upsert(Record("Y", "item1", sample_no="S9"))
    token_ab = store.inspect("A").token
    token_xy = store.inspect("X").token
    assert store.confirm(token_ab) is True
    assert store.confirm(token_xy) is True
    # 只动 AB 组：修改文本 + 增删临时成员。
    store.upsert(Record("A", "item1", sample_no="S1", text="changed"))
    store.upsert(Record("TMP", "item1", sample_no="S1"))
    store.remove("TMP")
    assert store.confirm(token_ab) is False
    assert store.inspect("A").releasable is False
    # XY 组完全不受影响，token 与确认保持有效。
    assert store.confirm(token_xy) is True
    assert store.inspect("X").token == token_xy
    assert store.inspect("X").releasable is True
    assert store.inspect("Y").releasable is True


def test_bridge_merge_and_split_requires_reconfirm() -> None:
    store = make_store()
    # 两个已确认的多成员组。
    store.upsert(Record("A1", "item1", sample_no="S1"))
    store.upsert(Record("A2", "item1", sample_no="S1"))
    store.upsert(Record("B1", "item1", instrument_no="I1"))
    store.upsert(Record("B2", "item1", instrument_no="I1"))
    token_a = store.inspect("A1").token
    token_b = store.inspect("B1").token
    assert store.confirm(token_a) is True
    assert store.confirm(token_b) is True
    assert store.inspect("A1").releasable is True
    assert store.inspect("B1").releasable is True

    # 桥接记录连接两组：合组不能继承任一旧组的确认。
    store.upsert(Record("BR", "item1", sample_no="S1", instrument_no="I1"))
    merged = store.inspect("BR")
    assert merged.members == frozenset({"A1", "A2", "B1", "B2", "BR"})
    assert merged.releasable is False
    assert store.confirm(token_a) is False
    assert store.confirm(token_b) is False
    # 合组重新确认后放行。
    merged_token = store.inspect("A1").token
    assert store.confirm(merged_token) is True
    assert store.inspect("B2").releasable is True

    # 删除桥接记录恢复两个组：拆组同样不继承确认，成员不遗漏不重复。
    store.remove("BR")
    group_a = store.inspect("A1")
    group_b = store.inspect("B1")
    assert group_a.members == frozenset({"A1", "A2"})
    assert group_b.members == frozenset({"B1", "B2"})
    assert group_a.releasable is False
    assert group_b.releasable is False
    assert store.confirm(merged_token) is False
    # 两组各自重新确认后独立放行。
    assert store.confirm(group_a.token) is True
    assert store.confirm(group_b.token) is True
    assert store.inspect("A2").releasable is True
    assert store.inspect("B2").releasable is True


def test_member_removal_invalidates_remaining_group() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1"))
    store.upsert(Record("C", "item1", sample_no="S1"))
    token = store.inspect("A").token
    assert store.confirm(token) is True
    store.remove("C")
    assert store.inspect("A").members == frozenset({"A", "B"})
    assert store.inspect("A").releasable is False
    assert store.confirm(token) is False
