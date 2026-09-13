"""候选人数据来源适配器。

把"候选人从哪来"这件事抽象成统一接口,便于扩展。

内置的 ``manual`` 适配器走文件导入(CSV / JSON),零风险、不碰平台接口。
如果你确实需要对接浏览器自动化,请自己实现 ``CandidateSource`` 子类,
并**自行确认**这样做符合目标平台的用户协议与当地法律法规。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Candidate


class CandidateSource(ABC):
    """候选人数据源接口。"""

    #: 适配器名称,CLI 里用它来选择来源
    name: str = "base"

    @abstractmethod
    def load(self) -> list[Candidate]:
        """返回候选人列表。实现方负责处理自己的解析与异常。"""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试输出
        return f"<{type(self).__name__} name={self.name!r}>"
