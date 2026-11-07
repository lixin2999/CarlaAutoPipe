"""风险操作二次确认对话框：注入 / 覆盖 / 回滚前展示差异清单。

差异清单来自 inject 报告的 details.diff（新增 / 覆盖文件列表）。
"""

from __future__ import annotations

from typing import Dict, List

from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListWidget,
                             QVBoxLayout)


class ConfirmDiffDialog(QDialog):
    """展示 新增/覆盖 文件清单，二次确认后才允许继续。"""

    def __init__(self, title: str, diff: Dict[str, List[str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 420)
        added = diff.get("added", [])
        overwritten = diff.get("overwritten", [])
        if isinstance(added, int):        # 兼容摘要模式（计数）
            added = [f"(共 {added} 个新增文件)"] if added else []
        if isinstance(overwritten, int):
            overwritten = [f"(共 {overwritten} 个覆盖文件)"] if overwritten else []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>{title}</b><br>新增 {len(added)} 个文件，覆盖 {len(overwritten)} 个文件。<br>"
            "注入前将自动快照备份，失败可一键回滚。请确认差异清单后继续。"))
        lst = QListWidget()
        for f in overwritten:
            lst.addItem(f"覆盖  {f}")
        for f in added:
            lst.addItem(f"新增  {f}")
        layout.addWidget(lst)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def confirm(title: str, diff: Dict[str, List[str]], parent=None) -> bool:
        dlg = ConfirmDiffDialog(title, diff, parent)
        return dlg.exec_() == QDialog.Accepted
