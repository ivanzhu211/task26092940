"""分组行为测试：匹配规则、传递闭包、改键与删除导致的合组/拆组。"""

import pytest

from dupcheck import DuplicateReviewStore, Record


def make_store() -> DuplicateReviewStore:
    return DuplicateReviewStore()


def members_of(store: DuplicateReviewStore, record_id: str) -> frozenset[str]:
    return store.inspect(record_id).members


def test_same_sample_no_groups_together() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1"))
    assert members_of(store, "A") == frozenset({"A", "B"})


def test_same_instrument_no_groups_together() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", instrument_no="I1"))
    store.upsert(Record("B", "item1", instrument_no="I1"))
    assert members_of(store, "A") == frozenset({"A", "B"})


def test_key_types_do_not_cross_match() -> None:
    store = make_store()
    # 样品登记号与仪器原始记录号取值相同也不能互相匹配。
    store.upsert(Record("A", "item1", sample_no="X1"))
    store.upsert(Record("B", "item1", instrument_no="X1"))
    assert members_of(store, "A") == frozenset({"A"})
    assert members_of(store, "B") == frozenset({"B"})


def test_different_item_does_not_match() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item2", sample_no="S1"))
    assert members_of(store, "A") == frozenset({"A"})
    assert members_of(store, "B") == frozenset({"B"})


def test_missing_keys_do_not_match() -> None:
    store = make_store()
    store.upsert(Record("A", "item1"))
    store.upsert(Record("B", "item1"))
    store.upsert(Record("C", "item1", sample_no="S1"))
    store.upsert(Record("D", "item1", instrument_no="I1"))
    assert members_of(store, "A") == frozenset({"A"})
    assert members_of(store, "B") == frozenset({"B"})
    assert members_of(store, "C") == frozenset({"C"})
    assert members_of(store, "D") == frozenset({"D"})


def test_transitive_closure_grouping() -> None:
    store = make_store()
    # A-B 共享样品登记号，B-C 共享仪器原始记录号，A 与 C 无相同键。
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1", instrument_no="I9"))
    store.upsert(Record("C", "item1", instrument_no="I9"))
    expected = frozenset({"A", "B", "C"})
    assert members_of(store, "A") == expected
    assert members_of(store, "B") == expected
    assert members_of(store, "C") == expected


def test_upsert_replaces_and_splits_old_group() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1"))
    assert members_of(store, "A") == frozenset({"A", "B"})
    # 改键后 A 离开旧组。
    store.upsert(Record("A", "item1", sample_no="S2"))
    assert members_of(store, "A") == frozenset({"A"})
    assert members_of(store, "B") == frozenset({"B"})


def test_upsert_new_keys_join_existing_group() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S2"))
    assert members_of(store, "A") == frozenset({"A"})
    # B 改键后与 A 相连。
    store.upsert(Record("B", "item1", sample_no="S1"))
    assert members_of(store, "A") == frozenset({"A", "B"})


def test_remove_updates_group() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1"))
    store.upsert(Record("C", "item1", sample_no="S1"))
    assert store.remove("B") is True
    assert members_of(store, "A") == frozenset({"A", "C"})
    assert store.remove("B") is False


def test_remove_bridge_splits_group() -> None:
    store = make_store()
    store.upsert(Record("A", "item1", sample_no="S1"))
    store.upsert(Record("B", "item1", sample_no="S1", instrument_no="I9"))
    store.upsert(Record("C", "item1", instrument_no="I9"))
    assert members_of(store, "A") == frozenset({"A", "B", "C"})
    store.remove("B")
    assert members_of(store, "A") == frozenset({"A"})
    assert members_of(store, "C") == frozenset({"C"})


def test_inspect_unknown_id_raises() -> None:
    store = make_store()
    with pytest.raises(KeyError):
        store.inspect("missing")
