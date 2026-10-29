"""Dialog for choosing which telegram-mcp tools are exposed (TELEGRAM_EXPOSED_TOOLS)."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..core.exposure import (
    ACCOUNT_WIDE_TOOLS,
    ExposureError,
    ExposurePolicy,
    from_selection,
    privacy_preset,
)
from ..core.toolscan import MODULE_LABELS, ToolInfo, as_flags


class ToolsDialog(QDialog):
    def __init__(self, tools: list[ToolInfo], current: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("工具权限：AI 能用哪些功能")
        self.resize(720, 640)
        self.tools = tools
        self.flags = as_flags(tools)
        self.result_policy: ExposurePolicy | None = None

        try:
            policy = ExposurePolicy.parse(current) if current else privacy_preset(self.flags)
            if policy.problems(self.flags):
                raise ExposureError("; ".join(policy.problems(self.flags)))
            selected = policy.exposed(self.flags)
            self.parse_note = ""
        except ExposureError as exc:
            selected = privacy_preset(self.flags).exposed(self.flags)
            self.parse_note = f"原来的设置无效（{exc}），已换成推荐设置。"

        intro = QLabel(
            "勾选的工具 AI 才能调用。<b>推荐</b>：只读工具 + 屏蔽通讯录、草稿、全局搜索这类"
            "能看到整个账号的工具（聊天白名单管不住它们）。写入类工具（发消息、删消息、管理群）"
            "默认全部关闭，打开前请想清楚。"
        )
        intro.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["工具", "说明"])
        self.tree.setColumnWidth(0, 300)
        by_module: dict[str, list[ToolInfo]] = defaultdict(list)
        for t in tools:
            by_module[t.module].append(t)
        self._items: dict[str, QTreeWidgetItem] = {}
        for module in sorted(by_module):
            for read_only in (True, False):
                group = [t for t in by_module[module] if t.read_only == read_only]
                if not group:
                    continue
                label = MODULE_LABELS.get(module, module) + (
                    "（只读）" if read_only else "（会修改账号）"
                )
                parent_item = QTreeWidgetItem([label])
                parent_item.setFlags(
                    parent_item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsAutoTristate
                )
                self.tree.addTopLevelItem(parent_item)
                for t in sorted(group, key=lambda x: x.name):
                    note = t.title
                    if t.name in ACCOUNT_WIDE_TOOLS:
                        note = f"⚠ 整个账号范围：{ACCOUNT_WIDE_TOOLS[t.name]}"
                    elif not t.read_only:
                        note = f"✎ 写入：{t.title}" if t.title else "✎ 写入"
                    item = QTreeWidgetItem([t.name, note])
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        0, Qt.CheckState.Checked if t.name in selected else Qt.CheckState.Unchecked
                    )
                    parent_item.addChild(item)
                    self._items[t.name] = item
                parent_item.setExpanded(not read_only or module in ("contacts", "folders"))

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        if self.parse_note:
            self.summary.setText(self.parse_note)

        preset_btn = QPushButton("恢复推荐设置")
        preset_btn.clicked.connect(self._apply_preset)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.summary)
        row = QHBoxLayout()
        row.addWidget(preset_btn)
        row.addStretch(1)
        row.addWidget(buttons)
        lay.addLayout(row)
        self.tree.itemChanged.connect(lambda *_: self._update_summary())
        self._update_summary()

    def selected(self) -> set[str]:
        return {n for n, it in self._items.items() if it.checkState(0) == Qt.CheckState.Checked}

    def _apply_preset(self) -> None:
        chosen = privacy_preset(self.flags).exposed(self.flags)
        for name, item in self._items.items():
            item.setCheckState(
                0, Qt.CheckState.Checked if name in chosen else Qt.CheckState.Unchecked
            )

    def _update_summary(self) -> None:
        sel = self.selected()
        writes = sorted(n for n in sel if not self.flags[n])
        text = f"已开启 {len(sel)} / {len(self.flags)} 个工具。"
        if writes:
            text += " 其中写入类：" + "、".join(writes)
        self.summary.setText(text)

    def _accept(self) -> None:
        sel = self.selected()
        if not sel:
            QMessageBox.warning(self, "工具权限", "至少开启一个工具。")
            return
        writes = sorted(n for n in sel if not self.flags[n])
        if writes:
            ok = QMessageBox.question(
                self,
                "确认开启写入工具",
                "这些工具会以你的身份修改 Telegram（发消息、删除、管理群等）：\n\n"
                + "\n".join(writes)
                + "\n\n确定要开启吗？",
            )
            if ok != QMessageBox.StandardButton.Yes:
                return
        self.result_policy = from_selection(self.flags, sel)
        self.accept()
