"""GUI 应用装配：QApplication 创建与全局样式（与入口 main 分离，便于测试导入）。"""

from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from .main_window import MainWindow

APP_TITLE = "CARLA 资产自动化导入工具"
APP_VERSION = "V1.0.0"


def create_app(argv: list | None = None) -> QApplication:
    """创建并返回已装配主窗口的 QApplication（不进入事件循环）。"""
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    window = MainWindow()
    window.show()
    # 保持引用，防止被垃圾回收
    app._carla_main_window = window  # noqa: SLF001
    return app
