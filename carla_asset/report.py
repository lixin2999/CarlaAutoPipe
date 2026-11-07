"""统一 JSON 报告模型。

GUI 薄壳契约（V1.4 §5.2）：GUI 只解析 ``--report=json`` 产出的本报告文件，
不解析标准输出。报告结构同时供 CI 归档。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from .constants import ExitCode, Level, REPORT_SCHEMA_VERSION


@dataclass
class Issue:
    """单条诊断项：级别、错误码、描述、修复建议、关联文件（可定位跳转）。"""

    level: str                                # ERROR / WARNING / INFO
    code: str                                 # 机器可读错误码，如 VEH_UNIT_NOT_CM
    message: str                              # 人类可读描述
    suggestion: str = ""                      # 修复建议
    file: Optional[str] = None                # 关联资产/Manifest 路径（POSIX 风格）
    line: Optional[int] = None                # 关联 Manifest 行号（GUI 高亮跳转）

    def __post_init__(self) -> None:
        if self.file:
            # 跨平台正斜杠归一化
            self.file = Path(self.file).as_posix()


@dataclass
class Report:
    """一次命令执行的完整结果。"""

    command: str
    exit_code: int = int(ExitCode.SUCCESS)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    duration_sec: Optional[float] = None
    asset_name: Optional[str] = None          # vehicle.{make}.{model} 或 map name
    issues: List[Issue] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)   # 产出物路径（POSIX）
    details: dict = field(default_factory=dict)          # 命令自定义扩展数据

    # -- 便捷构造 ----------------------------------------------------------
    def add_error(self, code: str, message: str, suggestion: str = "",
                  file: Optional[str] = None, line: Optional[int] = None) -> None:
        self.issues.append(Issue(Level.ERROR, code, message, suggestion, file, line))

    def add_warning(self, code: str, message: str, suggestion: str = "",
                    file: Optional[str] = None) -> None:
        self.issues.append(Issue(Level.WARNING, code, message, suggestion, file))

    def add_info(self, code: str, message: str, suggestion: str = "") -> None:
        self.issues.append(Issue(Level.INFO, code, message, suggestion))

    @property
    def has_error(self) -> bool:
        return any(i.level == Level.ERROR for i in self.issues)

    def counts(self) -> dict:
        c = {Level.ERROR: 0, Level.WARNING: 0, Level.INFO: 0}
        for i in self.issues:
            c[i.level] = c.get(i.level, 0) + 1
        return c

    def finish(self, exit_code: Optional[int] = None) -> "Report":
        self.finished_at = time.time()
        self.duration_sec = round(self.finished_at - self.started_at, 3)
        if exit_code is not None:
            self.exit_code = int(exit_code)
        elif self.has_error and self.exit_code == int(ExitCode.SUCCESS):
            self.exit_code = int(ExitCode.ASSET_VALIDATION_FAIL)
        return self

    # -- 序列化 ------------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["schema_version"] = REPORT_SCHEMA_VERSION
        d["issue_counts"] = self.counts()
        return d

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path) -> "Report":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        issues = [Issue(**i) for i in data.pop("issues", [])]
        data.pop("schema_version", None)
        data.pop("issue_counts", None)
        rpt = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        rpt.issues = issues
        return rpt


def environment_error(command: str, code: str, message: str, suggestion: str) -> Report:
    """构造 ENVIRONMENT_ERROR（退出码 3）标准报告。"""
    rpt = Report(command=command, exit_code=int(ExitCode.ENVIRONMENT_ERROR))
    rpt.add_error(code, message, suggestion)
    return rpt.finish()
