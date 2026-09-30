"""检验结果重复分组与二次确认引擎（单进程内存实现）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class Record:
    """一条检验结果记录。sample_no / instrument_no 为 None 表示键缺失，不参与匹配。"""

    record_id: str
    item: str  # 检测项目
    sample_no: str | None = None  # 样品登记号
    instrument_no: str | None = None  # 仪器原始记录号
    text: str = ""  # 结果文本


@dataclass(frozen=True)
class Inspection:
    """Inspect 的返回结果。"""

    members: frozenset[str]  # 当前组全部成员 ID
    token: str  # 不透明 token，同组成员共享
    releasable: bool  # 是否允许进入抽样复核


class DuplicateReviewStore:
    """维护记录的分组与确认状态。"""

    def __init__(self) -> None:
        self._records: dict[str, Record] = {}
        # 键索引：("sample"|"instrument", item, value) -> 持有该键的记录 ID 集合。
        # 只存键到成员集合的映射，不展开记录对，空间为 O(记录数)。
        self._key_index: dict[tuple[str, str, str], set[str]] = {}
        self._groups: dict[str, _Group] = {}  # 记录 ID -> 所属组
        self._tokens: dict[str, _Group] = {}  # 当前有效 token -> 组

    def upsert(self, record: Record) -> None:
        """新增或完整替换一条记录，每次成功调用均产生新修订。"""
        if record.record_id in self._records:
            self._remove(record.record_id)
        self._records[record.record_id] = record
        keys = list(self._keys_of(record))
        for key in keys:
            self._key_index.setdefault(key, set()).add(record.record_id)
        # 新记录通过键命中的全部现有组需要合并。
        # 同一键下的记录必属同一组，每桶任取一个成员即可定位组，
        # 无需遍历桶内全部旧成员。
        hit_groups: dict[int, _Group] = {}
        for key in keys:
            bucket = self._key_index[key]
            probe = record.record_id
            for other_id in bucket:
                if other_id != record.record_id:
                    probe = other_id
                    break
            if probe != record.record_id:
                group = self._groups[probe]
                hit_groups[id(group)] = group
        if not hit_groups:
            group = _Group()
            group.members.add(record.record_id)
            self._groups[record.record_id] = group
            return
        # 并到最大的组上，只搬移较小组的成员，不重新遍历大组旧成员。
        survivor = max(hit_groups.values(), key=lambda g: len(g.members))
        for other in hit_groups.values():
            if other is survivor:
                continue
            self._invalidate(other)
            for member_id in other.members:
                self._groups[member_id] = survivor
            survivor.members |= other.members
            other.members = set()
        self._invalidate(survivor)
        survivor.members.add(record.record_id)
        self._groups[record.record_id] = survivor

    def remove(self, record_id: str) -> bool:
        """删除记录，立即更新分组。记录不存在时返回 False。"""
        if record_id not in self._records:
            return False
        self._remove(record_id)
        return True

    def inspect(self, record_id: str) -> Inspection:
        """返回当前组成员、token 与放行状态。记录不存在时抛出 KeyError。"""
        if record_id not in self._records:
            raise KeyError(record_id)
        group = self._groups[record_id]
        if group.token is None:
            group.token = uuid.uuid4().hex
            self._tokens[group.token] = group
        releasable = len(group.members) == 1 or group.confirmed
        return Inspection(frozenset(group.members), group.token, releasable)

    def confirm(self, token: str) -> bool:
        """确认 token 对应的整组记录均可独立保留。过期 token 返回 False。"""
        group = self._tokens.get(token)
        if group is None:
            return False
        group.confirmed = True
        return True

    # ---- 内部实现 ----

    @staticmethod
    def _keys_of(record: Record) -> Iterator[tuple[str, str, str]]:
        if record.sample_no is not None:
            yield ("sample", record.item, record.sample_no)
        if record.instrument_no is not None:
            yield ("instrument", record.item, record.instrument_no)

    def _invalidate(self, group: "_Group") -> None:
        """撤销组的确认状态，并让旧 token 永久失效。"""
        if group.token is not None:
            self._tokens.pop(group.token, None)
            group.token = None
        group.confirmed = False

    def _remove(self, record_id: str) -> None:
        record = self._records.pop(record_id)
        for key in self._keys_of(record):
            bucket = self._key_index[key]
            bucket.discard(record_id)
            if not bucket:
                del self._key_index[key]
        old_group = self._groups.pop(record_id)
        old_group.members.discard(record_id)
        self._invalidate(old_group)
        remaining = old_group.members
        if len(remaining) <= 1:
            return
        # 删除可能导致旧组拆开：只在旧组成员范围内重新计算连通分量，
        # 不触碰任何无关组。拆出的每个组都是未确认的新状态。
        components = self._components(remaining)
        if len(components) == 1:
            return  # 未拆开，old_group 继续承载剩余成员
        old_group.members = components[0]
        for component in components[1:]:
            new_group = _Group()
            new_group.members = component
            for member_id in component:
                self._groups[member_id] = new_group

    def _components(self, member_ids: set[str]) -> list[set[str]]:
        """在 member_ids 内部按共享键计算连通分量（记录-键二部图 BFS）。"""
        unseen = set(member_ids)
        components: list[set[str]] = []
        while unseen:
            start = unseen.pop()
            component = {start}
            stack = [start]
            while stack:
                current = stack.pop()
                for key in self._keys_of(self._records[current]):
                    for neighbour in self._key_index.get(key, ()):
                        if neighbour in unseen:
                            unseen.discard(neighbour)
                            component.add(neighbour)
                            stack.append(neighbour)
            components.append(component)
        return components


class _Group:
    """一个复核组：成员集合 + 确认状态 + 当前 token。"""

    __slots__ = ("members", "token", "confirmed")

    def __init__(self) -> None:
        self.members: set[str] = set()
        self.token: str | None = None
        self.confirmed: bool = False
