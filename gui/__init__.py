"""PyQt5 GUI 薄壳包。

严格薄壳原则（V1.4 §5.2）：本包不承载任何业务逻辑，仅通过 subprocess
调用 carla-asset CLI，并解析 ``--report`` 写出的 JSON 报告渲染界面。
"""

__version__ = "V1.0.1"
