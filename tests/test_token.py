"""确认与token失效语义。"""

from dupreview import DuplicateReviewStore, Record


def rec(id, item="铅含量", sample=None, raw=None, text="0.01"):
    return Record(id=id, item=item, sample_no=sample, raw_no=raw, text=text)


def make_two_groups():
    """组1: a1-a2；组2: b1-b2。各自确认后返回。"""
    s = DuplicateReviewStore()
    s.upsert(rec("a1", sample="SA"))
    s.upsert(rec("a2", sample="SA"))
    s.upsert(rec("b1", sample="SB"))
    s.upsert(rec("b2", sample="SB"))
    ta = s.inspect("a1").token
    tb = s.inspect("b1").token
    assert s.confirm(ta) and s.confirm(tb)
    assert s.inspect("a1").allowed and s.inspect("b1").allowed
    return s, ta, tb


def test_text_only_revision_invalidates_token():
    s, ta, tb = make_two_groups()
    # 仅修改结果文本也必须失效
    s.upsert(rec("a1", sample="SA", text="0.02"))
    assert s.inspect("a1").allowed is False
    assert s.confirm(ta) is False  # 旧token永久失效
    # 未受影响组的token仍然有效
    assert s.inspect("b1").token == tb
    assert s.inspect("b1").allowed is True
    assert s.confirm(tb) is True


def test_add_then_remove_temp_member_does_not_revive_token():
    s, ta, tb = make_two_groups()
    # 添加再移除临时成员，即使恢复原成员集合，旧token也不能复活
    s.upsert(rec("tmp", sample="SA"))
    assert s.inspect("a1").members == ("a1", "a2", "tmp")
    s.remove("tmp")
    assert s.inspect("a1").members == ("a1", "a2")
    assert s.inspect("a1").allowed is False  # 确认已被撤销
    assert s.confirm(ta) is False
    # 未受影响组不受影响
    assert s.inspect("b1").token == tb
    assert s.confirm(tb) is True


def test_stale_token_failure_has_no_side_effect():
    s, ta, tb = make_two_groups()
    s.upsert(rec("a1", sample="SA", text="0.02"))
    new_token = s.inspect("a1").token
    assert new_token != ta
    assert s.confirm(ta) is False  # 过期token失败
    # 失败不能改变任何组的状态：当前token仍未确认
    assert s.inspect("a1").allowed is False
    assert s.inspect("a1").token == new_token
    assert s.confirm(new_token) is True
    assert s.inspect("a1").allowed is True


def test_unknown_token_fails():
    s = DuplicateReviewStore()
    assert s.confirm("does-not-exist") is False


def test_key_change_splits_old_group_and_joins_new_group():
    s = DuplicateReviewStore()
    s.upsert(rec("a1", sample="SA"))
    s.upsert(rec("a2", sample="SA"))
    s.upsert(rec("b1", sample="SB"))
    s.upsert(rec("b2", sample="SB"))
    ta = s.inspect("a1").token
    tb = s.inspect("b1").token
    assert s.confirm(ta) and s.confirm(tb)

    # a2 改键：离开组A、加入组B
    s.upsert(rec("a2", sample="SB"))
    assert s.inspect("a1").members == ("a1",)
    assert s.inspect("a1").allowed is True  # 单成员组直接放行
    assert s.inspect("a2").members == ("a2", "b1", "b2")
    # 拆组与合组均不继承确认
    assert s.inspect("b1").allowed is False
    assert s.confirm(ta) is False
    assert s.confirm(tb) is False


def test_member_removal_invalidates_remaining_group():
    s = DuplicateReviewStore()
    s.upsert(rec("a", sample="S1"))
    s.upsert(rec("b", sample="S1"))
    s.upsert(rec("c", sample="S1"))
    token = s.inspect("a").token
    assert s.confirm(token)
    s.remove("c")
    assert s.inspect("a").members == ("a", "b")
    assert s.inspect("a").allowed is False
    assert s.confirm(token) is False


def test_new_revision_of_singleton_requires_nothing_but_resets_token():
    s = DuplicateReviewStore()
    s.upsert(rec("a", sample="S1"))
    old_token = s.inspect("a").token
    s.upsert(rec("a", sample="S1", text="0.05"))
    insp = s.inspect("a")
    assert insp.allowed is True  # 单成员组始终放行
    assert insp.token != old_token  # 但旧token仍被撤销
    assert s.confirm(old_token) is False


def test_reconfirm_after_invalidation_issues_persistent_token():
    s, ta, _ = make_two_groups()
    s.upsert(rec("a1", sample="SA", text="0.02"))
    new_token = s.inspect("a1").token
    assert s.confirm(new_token) is True
    assert s.inspect("a2").allowed is True
    assert s.inspect("a2").token == new_token
