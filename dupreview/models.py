"""数据模型：检测记录与检查结果。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Record:
    """一条检测结果记录。

    上游已完成字段标准化；sample_no / raw_no 为 None 表示该键缺失，
    缺失键不参与重复匹配。
    """

    id: str                   # 记录ID
    item: str                 # 检测项目
    sample_no: Optional[str]  # 样品登记号
    raw_no: Optional[str]     # 仪器原始记录号
    text: str                 # 结果文本


@dataclass(frozen=True)
class Inspection:
    """Inspect(id) 的返回结果。"""

    members: tuple[str, ...]  # 当前组全部成员ID（排序后）
    token: str                # 不透明token，同组成员共享当前token
    allowed: bool             # 是否允许进入抽样复核
