"""GUI 入口：carla-asset-gui（pyproject 入口点 gui.main:main）。

GUI 为薄壳：不承载任何业务逻辑，仅通过 subprocess 调用 CLI 并解析
--report JSON 渲染界面（V1.4 §5.2）。
"""

from __future__ import annotations

import sys


def main(argv: list | None = None) -> int:
    try:
        from .app import create_app
    except ImportError as e:  # pragma: no cover - 依赖缺失路径
        print(f"[FATAL] GUI 依赖缺失（pip install PyQt5 后重试）: {e}",
              file=sys.stderr)
        return 3
    try:
        app = create_app(argv)
    except Exception as e:  # noqa: BLE001 - 启动期兜底提示
        print(f"[FATAL] GUI 启动失败: {e}", file=sys.stderr)
        return 3
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
