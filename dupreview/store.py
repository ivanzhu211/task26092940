"""重复分组与二次确认的核心存储（单进程内存实现）。"""

from __future__ import annotations

import uuid
from typing import Optional

from .models import Inspection, Record

# 索引键的种类：两类键不能互相匹配。
_KIND_SAMPLE = 0  # 样品登记号
_KIND_RAW = 1     # 仪器原始记录号


class _Group:
    """一个复核组：成员集合 + 当前确认状态。

    token 为 None 表示当前组状态尚未签发token（或刚被失效）。
    """

    __slots__ = ("members", "token", "confirmed")

    def __init__(self) -> None:
        self.members: set[str] = set()
        self.token: Optional[str] = None
        self.confirmed: bool = False


class DuplicateReviewStore:
    """维护记录的疑似重复分组，并对分组提供二次确认语义。

    内部结构：
    - _records: id -> Record
    - _index: (kind, item, key) -> 共享该键的记录id集合。
      同一集合内的记录两两相关，因此必属同一组；存储量随记录数
      线性增长，与重复对数量无关。
    - _group_of: id -> 所属 _Group
    - _tokens: 当前有效token -> 所属 _Group（过期token被移除）
    """

    def __init__(self) -> None:
        self._records: dict[str, Record] = {}
        self._index: dict[tuple[int, str, str], set[str]] = {}
        self._group_of: dict[str, _Group] = {}
        self._tokens: dict[str, _Group] = {}

    # ---------- 内部工具 ----------

    @staticmethod
    def _index_keys(record: Record) -> list[tuple[int, str, str]]:
        keys = []
        if record.sample_no is not None:
            keys.append((_KIND_SAMPLE, record.item, record.sample_no))
        if record.raw_no is not None:
            keys.append((_KIND_RAW, record.item, record.raw_no))
        return keys

    def _invalidate(self, group: _Group) -> None:
        """使组的当前确认与token永久失效。"""
        if group.token is not None:
            self._tokens.pop(group.token, None)
            group.token = None
        group.confirmed = False

    def _remove_internal(self, record_id: str) -> None:
        record = self._records.pop(record_id)
        for key in self._index_keys(record):
            bucket = self._index[key]
            bucket.discard(record_id)
            if not bucket:
                del self._index[key]

        group = self._group_of.pop(record_id)
        group.members.discard(record_id)
        # 任何成员变动都撤销该组确认；拆组后的各组也不继承确认。
        self._invalidate(group)

        remaining = group.members
        if len(remaining) <= 1:
            if not remaining:
                return  # 组已空，对象随引用消失
            # 只剩一个成员，保持原（已失效的）组对象即可
            return

        # 旧组可能拆开：只在受影响旧组的成员内做连通分量划分，
        # 不枚举无关组的成员。按“键桶”扩展，每个桶至多遍历一次。
        components = self._split_components(remaining)
        if len(components) == 1:
            return  # 组仍连通，成员集合未变

        # 最大分量复用原组对象，避免再次搬运其成员
        components.sort(key=len, reverse=True)
        group.members = components[0]
        for component in components[1:]:
            new_group = _Group()
            new_group.members = component
            for member_id in component:
                self._group_of[member_id] = new_group

    def _split_components(self, member_ids: set[str]) -> list[set[str]]:
        """在 member_ids 的诱导子图上求连通分量。"""
        unvisited = set(member_ids)
        components: list[set[str]] = []
        processed_buckets: set[tuple[int, str, str]] = set()
        while unvisited:
            component: set[str] = set()
            stack = [unvisited.pop()]
            while stack:
                current = stack.pop()
                if current in component:
                    continue
                component.add(current)
                for key in self._index_keys(self._records[current]):
                    if key in processed_buckets:
                        continue
                    processed_buckets.add(key)
                    for neighbor in self._index.get(key, ()):
                        if neighbor in unvisited:
                            unvisited.discard(neighbor)
                            stack.append(neighbor)
            components.append(component)
        return components

    # ---------- 对外操作 ----------

    def upsert(self, record: Record) -> None:
        """新增或完整替换一条记录。

        每次成功调用均产生新修订：即使只改结果文本，也会撤销
        旧组确认并使旧token失效。改键可能使旧组拆开、新组连接。
        """
        if record.id in self._records:
            self._remove_internal(record.id)

        self._records[record.id] = record
        index_keys = self._index_keys(record)

        # 同一索引桶内的记录必属同一组，任取一个成员即可定位该组，
        # 无需遍历桶内全部成员。
        neighbor_groups: dict[int, _Group] = {}
        for key in index_keys:
            bucket = self._index.get(key)
            if bucket:
                neighbor = self._group_of[next(iter(bucket))]
                neighbor_groups[id(neighbor)] = neighbor

        for key in index_keys:
            self._index.setdefault(key, set()).add(record.id)

        if not neighbor_groups:
            group = _Group()
            group.members.add(record.id)
            self._group_of[record.id] = group
            return

        # 合并所有被连通的组：最大组作为存续组，避免搬运其成员；
        # 合组不继承任一旧组的确认。
        groups = sorted(neighbor_groups.values(),
                        key=lambda g: len(g.members), reverse=True)
        survivor = groups[0]
        self._invalidate(survivor)
        survivor.members.add(record.id)
        self._group_of[record.id] = survivor
        for other in groups[1:]:
            self._invalidate(other)
            for member_id in other.members:
                self._group_of[member_id] = survivor
            survivor.members.update(other.members)

    def remove(self, record_id: str) -> None:
        """删除一条记录，立即更新剩余记录的分组。"""
        if record_id not in self._records:
            raise KeyError(f"记录不存在: {record_id!r}")
        self._remove_internal(record_id)

    def inspect(self, record_id: str) -> Inspection:
        """返回当前组全部成员ID、当前token与放行状态。

        同组成员得到同一当前token与放行状态。单成员组直接放行；
        多成员组只有在当前组状态被确认后才放行。
        """
        group = self._group_of.get(record_id)
        if group is None:
            raise KeyError(f"记录不存在: {record_id!r}")
        if group.token is None:
            group.token = uuid.uuid4().hex
            self._tokens[group.token] = group
        allowed = len(group.members) == 1 or group.confirmed
        return Inspection(
            members=tuple(sorted(group.members)),
            token=group.token,
            allowed=allowed,
        )

    def confirm(self, token: str) -> bool:
        """确认token对应的整组记录均可独立保留。

        过期token必须失败，且不能改变任何组的状态。
        """
        group = self._tokens.get(token)
        if group is None or group.token != token:
            return False
        group.confirmed = True
        return True
