"""主窗口：左侧步骤导航树 + 中部流式日志 + 下部错误卡片（V1.4 §5.2）。

业务逻辑零承载：所有动作映射为一条 CLI 命令，经 CliRunner 异步执行，
完成后仅解析 JSON 报告渲染界面。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QColor, QFont, QDesktopServices
from PyQt5.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                             QMainWindow, QProgressBar, QPushButton,
                             QSplitter, QTableWidget,
                             QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget, QMessageBox, QPlainTextEdit,
                             QLineEdit, QCheckBox)

from . import __version__
from .confirm_dialog import ConfirmDiffDialog
from .env_check import blocked_steps, env_status
from .preview import preview_diff
from .runner import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = REPO_ROOT / "reports"

# 步骤导航（与设计文档界面结构一致）
STEPS = [
    ("validate", "1. 前置校验", "validate"),
    ("rig", "2. 自动绑骨", "rig"),
    ("build", "3. 引擎导入", "build-vehicle"),
    ("register", "4. 工厂注册", "build-vehicle"),
    ("pack", "5. 打包", "pack"),
    ("inject", "6. 注入", "inject"),
    ("smoke", "7. 冒烟验证", "smoke"),
]

COLOR_DONE = QColor(0, 160, 0)
COLOR_FAIL = QColor(200, 0, 0)
COLOR_RUN = QColor(0, 90, 200)


class StepInputs(QWidget):
    """每个步骤的参数输入面板（简化：单行路径 + 选项）。"""

    def __init__(self, step_key: str, parent=None):
        super().__init__(parent)
        self.step_key = step_key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.pathEdit = QLineEdit()
        self.pathEdit.setPlaceholderText(self._placeholder())
        layout.addWidget(self.pathEdit, 1)
        self.extra = QCheckBox()
        self.extra.setText(self._extra_label())
        layout.addWidget(self.extra)
        self.browseBtn = QPushButton("浏览…")
        self.browseBtn.clicked.connect(self._browse)
        layout.addWidget(self.browseBtn)

    def _placeholder(self) -> str:
        return {
            "validate": "FBX 资产路径（--input）",
            "rig": "输入 FBX → 输出 FBX（用 ; 分隔两个路径）",
            "build": "Manifest 路径（manifests/vehicles/*.json）",
            "register": "Manifest 路径（同引擎导入，勾选 skip-factory 走通道 B）",
            "pack": "包名;源目录（如 su7;out/su7）",
            "inject": "资产包路径（zip/tar.gz/pak）",
            "smoke": "vehicle: xiaomi.su7 或 map: Town10",
        }.get(self.step_key, "参数")

    def _extra_label(self) -> str:
        return {
            "validate": "地图资产",
            "rig": "Y轴镜像",
            "build": "dry-run",
            "register": "skip-factory",
            "pack": "linux平台",
            "inject": "失败自动回滚",
            "smoke": "地图冒烟",
        }.get(self.step_key, "")

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "选择文件", str(REPO_ROOT))
        if p:
            self.pathEdit.setText(Path(p).as_posix())

    def build_args(self) -> Optional[list]:
        """把面板输入翻译为 CLI 参数；不合法返回 None。"""
        raw = self.pathEdit.text().strip().replace("\\", "/")
        kind = self.extra.isChecked()
        if not raw:
            return None
        parts = [s.strip() for s in raw.split(";")] if ";" in raw else [raw]
        k = self.step_key
        if k == "validate":
            return ["validate", "--type", "map" if kind else "vehicle",
                    "--input", parts[0]]
        if k == "rig":
            if len(parts) < 2:
                return None
            args = ["rig", "--fbx", parts[0], "--out", parts[1]]
            return args + (["--mirror-y"] if kind else [])
        if k in ("build", "register"):
            args = ["build-vehicle", "--manifest", parts[0]]
            if kind and k == "build":
                args.append("--dry-run")
            if kind and k == "register":
                args = ["build-vehicle", "--manifest", parts[0], "--skip-factory"]
            return args
        if k == "pack":
            if len(parts) < 2:
                return None
            return ["pack", "--pkg", parts[0], "--src", parts[1],
                    "--platform", "linux" if kind else "win"]
        if k == "inject":
            args = ["inject", "--pkg", parts[0], "--rollback-on-fail"]
            return args
        if k == "smoke":
            return ["smoke", "--type", "map" if kind else "vehicle",
                    "--name", parts[0]]
        return None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"CARLA 资产自动化导入工具 {__version__}")
        self.resize(1180, 760)
        self._runner: Optional[CliRunner] = None
        self._step_items: Dict[str, QTreeWidgetItem] = {}

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_nav())
        splitter.addWidget(self._build_center())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(splitter)
        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

        self._env_check()

    # ------------------------------------------------------------------ UI
    def _build_nav(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.addWidget(QLabel("<b>步骤导航</b>"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        for key, label, cmd in STEPS:
            item = QTreeWidgetItem([label])
            item.setData(0, Qt.UserRole, key)
            self.tree.addTopLevelItem(item)
            self._step_items[key] = item
            btn_row = StepInputs(key)
            btn_row.setToolTip(f"对应命令: carla-asset {cmd}")
            self.tree.setItemWidget(item, 0, btn_row)
        self.tree.setCurrentItem(self._step_items["validate"])
        lay.addWidget(self.tree)
        self.runBtn = QPushButton("▶ 执行当前步骤")
        self.runBtn.clicked.connect(self._run_current)
        self.cancelBtn = QPushButton("■ 取消")
        self.cancelBtn.clicked.connect(self._cancel)
        self.cancelBtn.setEnabled(False)
        lay.addWidget(self.runBtn)
        lay.addWidget(self.cancelBtn)
        wrap.setFixedWidth(430)
        return wrap

    def _build_center(self) -> QWidget:
        split = QSplitter(Qt.Vertical)
        # 中部流式日志
        log_wrap = QWidget()
        lay = QVBoxLayout(log_wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("<b>执行日志</b>（关键字高亮）"))
        self.logView = QPlainTextEdit()
        self.logView.setReadOnly(True)
        self.logView.setFont(QFont("Consolas", 9))
        lay.addWidget(self.logView)
        split.addWidget(log_wrap)
        # 下部错误卡片
        card_wrap = QWidget()
        lay2 = QVBoxLayout(card_wrap)
        lay2.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>诊断卡片</b>（点击行跳转关联文件）"))
        self.filterBox = QCheckBox("仅显示 ERROR")
        head.addWidget(self.filterBox)
        head.addStretch(1)
        lay2.addLayout(head)
        self.cardTable = QTableWidget(0, 4)
        self.cardTable.setHorizontalHeaderLabels(["级别", "错误码", "描述 / 修复建议", "位置"])
        self.cardTable.horizontalHeader().setSectionResizePolicy(2, QHeaderView.Stretch)
        self.cardTable.horizontalHeader().setSectionResizePolicy(3, QHeaderView.ResizeToContents)
        self.cardTable.verticalHeader().setVisible(False)
        self.cardTable.itemSelectionChanged.connect(self._jump_to_file)
        lay2.addWidget(self.cardTable)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        lay2.addWidget(self.progress)
        split.addWidget(card_wrap)
        split.setSizes([430, 300])
        return split

    # ------------------------------------------------------------ env check
    def _env_check(self) -> None:
        status = env_status()
        blocked = blocked_steps(status)
        hints = []
        for key, item in status.items():
            mark = "✓" if item["ok"] else "✗"
            hints.append(f"{mark} {item['label']}")
            if not item["ok"]:
                self._append_log(f"[环境] {item['message']}；{item['suggestion']}")
        for step, problems in blocked.items():
            if problems:
                it = self._step_items[step]
                it.setDisabled(True)
                it.setText(0, it.text(0) + "（环境缺失）")
        self.statusBar().showMessage("环境自检: " + "  ".join(hints))

    # ----------------------------------------------------------------- run
    def _run_current(self) -> None:
        cur = self.tree.currentItem()
        if cur is None:
            return
        step = cur.data(0, Qt.UserRole)
        widget = self.tree.itemWidget(cur, 0)
        if not isinstance(widget, StepInputs):
            return
        args = widget.build_args()
        if args is None:
            QMessageBox.warning(self, "参数不完整", "请填写该步骤所需参数（见输入框提示）")
            return
        # 注入/覆盖类风险操作：先展示差异清单二次确认（真实预览，只读不写目标）
        if args[0] == "inject":
            diff = preview_diff(args[1])
            if diff is None:
                diff = {"added": ["（预览不可用：包解析失败或 CARLA_ROOT 未配置/不存在）"],
                        "overwritten": []}
            if not ConfirmDiffDialog.confirm(
                    "注入确认 — 目标 CARLA 目录差异清单",
                    diff, self):
                return
        self._start(args, step)

    def _start(self, args: list, step: str) -> None:
        REPORT_DIR.mkdir(exist_ok=True)
        report = REPORT_DIR / f"gui_{args[0]}_{step}.json"
        self._current_step = step
        self._current_cmd = args[0]
        item = self._step_items[step]
        item.setForeground(0, COLOR_RUN)
        self._append_log(f"\n$ carla-asset {' '.join(args)}")
        self.progress.setVisible(True)
        self.runBtn.setEnabled(False)
        self.cancelBtn.setEnabled(True)
        self._runner = CliRunner(args, report, parent=self)
        self._runner.line_ready.connect(self._append_log)
        self._runner.finished_with_report.connect(self._on_finished)
        self._runner.start()

    def _cancel(self) -> None:
        if self._runner:
            self._runner.cancel()

    def _on_finished(self, code: int, report_path: str) -> None:
        self.progress.setVisible(False)
        self.runBtn.setEnabled(True)
        self.cancelBtn.setEnabled(False)
        item = self._step_items.get(getattr(self, "_current_step", ""), None)
        if item is not None:
            item.setForeground(0, COLOR_DONE if code == 0 else COLOR_FAIL)
        self.statusBar().showMessage(f"{self._current_cmd} 结束，退出码 {code}")
        report = CliRunner.load_report(report_path)
        self._render_cards(report)
        # inject 报告带 diff 时提示回滚快照位置
        if report and report.get("command") == "inject" and code != 0:
            snap = (report.get("details") or {}).get("diff")
            if snap:
                self._append_log("[GUI] 注入失败：如需手工回滚见报告中的快照路径")

    # -------------------------------------------------------------- render
    def _append_log(self, line: str) -> None:
        html = (line.replace("&", "&amp;").replace("<", "&lt;"))
        if "ERROR" in line:
            html = f'<span style="color:#c00">{html}</span>'
        elif "WARNING" in line:
            html = f'<span style="color:#b60">{html}</span>'
        elif line.startswith("$ "):
            html = f'<span style="color:#06c"><b>{html}</b></span>'
        self.logView.appendHtml(html)

    def _render_cards(self, report: Optional[dict]) -> None:
        self.cardTable.setRowCount(0)
        if not report:
            return
        issues = report.get("issues", [])
        if self.filterBox.isChecked():
            issues = [i for i in issues if i.get("level") == "ERROR"]
        for iss in issues:
            row = self.cardTable.rowCount()
            self.cardTable.insertRow(row)
            level = iss.get("level", "INFO")
            level_item = QTableWidgetItem(level)
            level_item.setForeground(
                COLOR_FAIL if level == "ERROR" else
                QColor(200, 120, 0) if level == "WARNING" else QColor(80, 80, 80))
            body = iss.get("message", "")
            if iss.get("suggestion"):
                body += f"\n↳ 修复建议: {iss['suggestion']}"
            body_item = QTableWidgetItem(body)
            body_item.setData(Qt.UserRole, json.dumps(iss, ensure_ascii=False))
            loc = iss.get("file") or ""
            if iss.get("line"):
                loc += f":{iss['line']}"
            self.cardTable.setItem(row, 0, level_item)
            self.cardTable.setItem(row, 1, QTableWidgetItem(iss.get("code", "")))
            self.cardTable.setItem(row, 2, body_item)
            pos_item = QTableWidgetItem(loc)
            pos_item.setData(Qt.UserRole, iss.get("file"))
            self.cardTable.setItem(row, 3, pos_item)

    def _jump_to_file(self) -> None:
        items = self.cardTable.selectedItems()
        if not items:
            return
        path_item = self.cardTable.item(items[0].row(), 3)
        target = path_item.data(Qt.UserRole) if path_item else None
        if target:
            p = Path(target)
            if not p.is_absolute():
                p = REPO_ROOT / p
            QDesktopServices.openUrl(QUrl.fromLocalFile(p.as_posix()))
            self.statusBar().showMessage(f"已请求打开: {target}")
