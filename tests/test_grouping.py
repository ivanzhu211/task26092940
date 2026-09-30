"""基础分组与放行语义。"""

import pytest

from dupreview import DuplicateReviewStore, Record


def rec(id, item="铅含量", sample=None, raw=None, text="0.01"):
    return Record(id=id, item=item, sample_no=sample, raw_no=raw, text=text)


def test_single_member_group_allowed_directly():
    s = DuplicateReviewStore()
    s.upsert(rec("a", sample="S1"))
    insp = s.inspect("a")
    assert insp.allowed is True
    assert insp.members == ("a",)


def test_same_sample_number_groups_together():
    s = DuplicateReviewStore()
    s.upsert(rec("a", sample="S1"))
    s.upsert(rec("b", sample="S1"))
    assert s.inspect("a").members == ("a", "b")
    assert s.inspect("a").allowed is False  # 多成员组未确认不放行


def test_same_raw_number_groups_together():
    s = DuplicateReviewStore()
    s.upsert(rec("a", raw="R1"))
    s.upsert(rec("b", raw="R1"))
    assert s.inspect("a").members == ("a", "b")


def test_transitive_closure_grouping():
    # A-B 共享样品号，B-C 共享原始记录号，A-C 无相同键仍同组
    s = DuplicateReviewStore()
    s.upsert(rec("a", sample="S1"))
    s.upsert(rec("b", sample="S1", raw="R9"))
    s.upsert(rec("c", raw="R9"))
    assert s.inspect("a").members == ("a", "b", "c")
    assert s.inspect("c").members == ("a", "b", "c")


def test_two_key_kinds_never_cross_match():
    # 样品登记号 "X1" 与仪器原始记录号 "X1" 字符串相同也不匹配
    s = DuplicateReviewStore()
    s.upsert(rec("a", sample="X1"))
    s.upsert(rec("b", raw="X1"))
    assert s.inspect("a").members == ("a",)
    assert s.inspect("b").members == ("b",)


def test_different_items_never_match():
    s = DuplicateReviewStore()
    s.upsert(rec("a", item="铅含量", sample="S1"))
    s.upsert(rec("b", item="镉含量", sample="S1"))
    assert s.inspect("a").members == ("a",)
    assert s.inspect("b").members == ("b",)


def test_missing_keys_not_matched():
    s = DuplicateReviewStore()
    s.upsert(rec("a", sample=None, raw=None))
    s.upsert(rec("b", sample=None, raw=None))
    assert s.inspect("a").members == ("a",)
    assert s.inspect("b").members == ("b",)


def test_same_group_members_share_token_and_status():
    s = DuplicateReviewStore()
    s.upsert(rec("a", sample="S1"))
    s.upsert(rec("b", sample="S1"))
    ia = s.inspect("a")
    ib = s.inspect("b")
    assert ia.token == ib.token
    assert ia.allowed == ib.allowed is False
    assert s.confirm(ia.token) is True
    assert s.inspect("a").allowed is True
    assert s.inspect("b").allowed is True
    # 确认后token保持不变
    assert s.inspect("a").token == ia.token


def test_remove_unknown_id_raises():
    s = DuplicateReviewStore()
    with pytest.raises(KeyError):
        s.remove("nope")


def test_inspect_unknown_id_raises():
    s = DuplicateReviewStore()
    with pytest.raises(KeyError):
        s.inspect("nope")


def test_remove_updates_grouping_immediately():
    s = DuplicateReviewStore()
    s.upsert(rec("a", sample="S1"))
    s.upsert(rec("b", sample="S1", raw="R9"))
    s.upsert(rec("c", raw="R9"))
    s.remove("b")  # 删除传递枢纽后 a 与 c 拆成两个单成员组
    assert s.inspect("a").members == ("a",)
    assert s.inspect("c").members == ("c",)
    assert s.inspect("a").allowed is True
    assert s.inspect("c").allowed is True
