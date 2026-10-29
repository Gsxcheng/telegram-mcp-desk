"""Dialog for choosing which chats telegram-mcp may read (TELEGRAM_ALLOWED_CHAT_IDS)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..core.allowlist import KIND_LABELS, Dialog, initial_selection

ORPHAN_NAME = "（对话列表里没找到，可能已退出）"


class ChatPickerDialog(QDialog):
    def __init__(self, dialogs: list[Dialog], current: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择 AI 能读的频道 / 群 / 机器人")
        self.resize(780, 600)
        checked_ids, orphans = initial_selection(current, dialogs)
        # Rows: (token written to .env, Dialog)
        self.rows: list[tuple[str, Dialog]] = [(d.id, d) for d in dialogs]
        self.rows += [(t, Dialog(t, ORPHAN_NAME, "unknown")) for t in orphans]
        self.checked: set[str] = set(checked_ids) | set(orphans)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称、用户名或 ID")
        self.show_private = QCheckBox("显示私聊")
        top = QHBoxLayout()
        top.addWidget(QLabel("搜索："))
        top.addWidget(self.search, 1)
        top.addWidget(self.show_private)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名称", "类型", "用户名", "ID"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 320)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 160)

        self.count = QLabel()
        note = QLabel("只有勾选的聊天能被 AI 读到。对话列表只在本机显示，不会发到任何地方。")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addWidget(note)
        bottom = QHBoxLayout()
        bottom.addWidget(self.count, 1)
        bottom.addWidget(buttons)
        lay.addLayout(bottom)

        self._filling = False
        self.search.textChanged.connect(self._fill)
        self.show_private.toggled.connect(self._fill)
        self.tree.itemChanged.connect(self._item_changed)
        self._fill()

    def _fill(self) -> None:
        self._filling = True
        self.tree.clear()
        q = self.search.text().strip().lower()
        for token, d in self.rows:
            is_checked = token in self.checked
            if d.kind == "user" and not self.show_private.isChecked() and not is_checked:
                continue
            if q and q not in f"{d.name} {d.username} {d.id}".lower():
                continue
            kind = KIND_LABELS.get(d.kind, d.kind) + ("（归档）" if d.archived else "")
            item = QTreeWidgetItem([d.name, kind, f"@{d.username}" if d.username else "", d.id])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, token)
            self.tree.addTopLevelItem(item)
        self._filling = False
        self._update_count()

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._filling or column != 0:
            return
        token = item.data(0, Qt.ItemDataRole.UserRole)
        if item.checkState(0) == Qt.CheckState.Checked:
            self.checked.add(token)
        else:
            self.checked.discard(token)
        self._update_count()

    def _update_count(self) -> None:
        self.count.setText(f"已选 {len(self.checked)} 个")

    def selected_tokens(self) -> list[str]:
        return [token for token, _ in self.rows if token in self.checked]

    def _accept(self) -> None:
        if not self.checked:
            QMessageBox.warning(
                self, "选择频道", "至少要勾选一个。一个都不选等于不设限制，AI 能读到你所有的聊天。"
            )
            return
        self.accept()
