# 检验结果重复分组与二次确认库

供质量管理系统决定哪些检测结果可以进入抽样复核。单进程内存实现，
不考虑并发调用与重启恢复。

## 运行全部测试

```bash
python3 -m pytest -q -s
```

（`-s` 用于显示规模场景的分阶段耗时报告。）

## 使用示例

```python
from dupreview import DuplicateReviewStore, Record

store = DuplicateReviewStore()
store.upsert(Record(id="r1", item="铅含量", sample_no="S1",
                    raw_no=None, text="0.01"))
store.upsert(Record(id="r2", item="铅含量", sample_no="S1",
                    raw_no="RAW9", text="0.02"))

insp = store.inspect("r1")   # members=("r1","r2"), allowed=False
store.confirm(insp.token)    # 整组二次确认
store.inspect("r2").allowed  # True

store.upsert(Record(id="r1", item="铅含量", sample_no="S1",
                    raw_no=None, text="0.03"))  # 任何修订使旧token失效
store.remove("r2")           # 删除后立即重新分组
```

## 匹配与分组规则

- 检测项目相同，且样品登记号相同**或**仪器原始记录号相同，构成疑似重复；
  两类键互不匹配，缺失键（`None`）不参与匹配。
- 重复关系按传递闭包分组；同组成员共享当前 token 与放行状态。
- 单成员组直接放行；多成员组确认当前 token 后才放行。
- 任何成员的新修订（含仅改结果文本）、加入、删除都撤销涉及组的确认，
  旧 token 永久失效；合组与拆组均不继承确认；未受影响的组不受影响。

## 复杂度

内部只维护：记录表、`(键种类, 检测项目, 键值) -> 记录id集合` 的索引、
每条记录的组指针、当前有效 token 表。存储为 O(记录数 × 每记录键数)，
与重复对数量无关（3 万条记录共享一个键时，对应索引桶只是一个
含 3 万元素的集合）。

| 操作 | 单个大组（n 为组大小） | 大量小组 |
| --- | --- | --- |
| Upsert 新增 | O(1)：每个键桶任取一个成员定位所属组，不遍历桶 | O(1) |
| Upsert 改键 / Remove | 在受影响旧组内求连通分量，O(旧组大小)；键桶按“每桶至多遍历一次”扩展，大组也是 O(n) 而非 O(n²) | O(小组大小)，与记录总数无关 |
| 合组 | 小组成员并入最大组，O(小组大小)，不搬运最大组成员 | O(组合大小) |
| Inspect | O(n)：返回全部成员需遍历并排序 | O(组大小) |
| Confirm | O(1) | O(1) |

空间：所有结构均为 O(记录数)；token 表只保存当前有效 token。
