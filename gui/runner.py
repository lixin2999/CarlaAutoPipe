"""CLI 执行器：QThread + subprocess 异步运行 carla-asset 命令。

只转发标准输出用于日志展示；结构化结果一律来自 JSON 报告文件。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

REPO_ROOT = Path(__file__).resolve().parent.parent


class CliRunner(QThread):
    """在后台线程执行一条 CLI 命令，流式发出日志行，结束时发出报告路径。"""

    line_ready = pyqtSignal(str)                 # stdout/stderr 行
    finished_with_report = pyqtSignal(int, str)  # (exit_code, report_path)

    def __init__(self, args: List[str], report_path: Path, parent=None):
        super().__init__(parent)
        # 统一以模块方式调用，避免依赖已安装的控制台脚本
        self.args = [sys.executable, "-m", "carla_asset.cli", *args,
                     "--report", str(report_path)]
        self.report_path = report_path
        self._proc: Optional[subprocess.Popen] = None

    def run(self) -> None:  # noqa: D102
        code = 2
        try:
            if self.report_path.exists():
                self.report_path.unlink()
            self._proc = subprocess.Popen(
                self.args, cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1)
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                self.line_ready.emit(line.rstrip())
            code = self._proc.wait()
        except OSError as e:
            self.line_ready.emit(f"[GUI] 进程启动失败: {e}")
            code = 2
        self.finished_with_report.emit(int(code), self.report_path.as_posix())

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    @staticmethod
    def load_report(path: str) -> Optional[dict]:
        p = Path(path)
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None
