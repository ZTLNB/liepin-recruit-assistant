"""候选人数据来源适配器。

内置 ``ManualImportSource`` 走本地文件导入。如需对接其他来源,
请实现 ``CandidateSource`` 子类,并自行确认合规性。
"""

from .base import CandidateSource
from .manual import ManualImportSource

#: 已注册的适配器:名称 -> 类
ADAPTERS: dict[str, type[CandidateSource]] = {
    ManualImportSource.name: ManualImportSource,
}

__all__ = ["CandidateSource", "ManualImportSource", "ADAPTERS"]
