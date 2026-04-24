from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QLineEdit, QComboBox, QTextEdit,
    QPushButton, QListWidget, QListWidgetItem, QMessageBox,
    QSpinBox, QInputDialog, QFrame,
)

from config_manager import ConfigManager, LANGUAGES
from translator import Translator

# ---------------------------------------------------------------------------
# Provider presets — base_url + common model list
# ---------------------------------------------------------------------------
PROVIDERS: dict[str, dict] = {
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "通义千问 (阿里云)": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-long", "qwen2.5-72b-instruct"],
    },
    "Moonshot / Kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    },
    "智谱 AI (GLM)": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4", "glm-4-air", "glm-3-turbo"],
    },
    "百度文心": {
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": ["ernie-4.0-8k", "ernie-3.5-8k", "ernie-speed-128k"],
    },
    "腾讯混元": {
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "models": ["hunyuan-turbos", "hunyuan-standard", "hunyuan-lite"],
    },
    "Claude (Anthropic)": {
        "base_url": "https://api.anthropic.com/v1",
        "models": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ],
    },
    "Gemini (Google)": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash"],
    },
    "Ollama (本地)": {
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen2.5:7b", "deepseek-r1:7b", "llama3.2", "mistral"],
    },
    "自定义": {
        "base_url": "",
        "models": [],
    },
}

# ---------------------------------------------------------------------------
# Stylesheet (same dark palette as floating window, adapted for a dialog)
# ---------------------------------------------------------------------------
STYLE = """
QDialog {
    background-color: #1e1e2e;
}
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 8px;
    background-color: #181825;
}
QTabBar::tab {
    background-color: #313244;
    color: #a6adc8;
    padding: 8px 18px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #cba6f7;
    color: #1e1e2e;
    font-weight: bold;
}
QTabBar::tab:hover:!selected { background-color: #45475a; }
QLineEdit, QSpinBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
}
QLineEdit:focus, QSpinBox:focus { border: 1px solid #cba6f7; }
QTextEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px;
}
QTextEdit:focus { border: 1px solid #cba6f7; }
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #585b70;
    border: 1px solid #45475a;
}
QPushButton {
    background-color: #cba6f7;
    color: #1e1e2e;
    border: none;
    border-radius: 6px;
    padding: 7px 18px;
    font-weight: bold;
}
QPushButton:hover { background-color: #d5b8ff; }
QPushButton:pressed { background-color: #b48ef0; }
QPushButton#secondary {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    font-weight: normal;
}
QPushButton#secondary:hover { background-color: #45475a; }
QPushButton#danger {
    background-color: #f38ba8;
    color: #1e1e2e;
}
QPushButton#danger:hover { background-color: #f5a0b8; }
QLabel { color: #cdd6f4; }
QLabel#hint {
    color: #6c7086;
    font-size: 11px;
}
QListWidget {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
}
QListWidget::item:selected { background-color: #585b70; }
QListWidget::item:hover { background-color: #45475a; }
"""


# ---------------------------------------------------------------------------
# Hotkey recorder widget
# ---------------------------------------------------------------------------
class HotkeyRecorder(QWidget):
    """Click 'Record', press a key combo, display the keyboard-lib string."""

    def __init__(self, initial: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.display = QLineEdit(initial)
        self.display.setReadOnly(True)
        self.display.setPlaceholderText("点击「录制」后按下快捷键…")
        layout.addWidget(self.display)

        self.btn = QPushButton("录制")
        self.btn.setObjectName("secondary")
        self.btn.setCheckable(True)
        self.btn.toggled.connect(self._on_toggled)
        self.btn.setFixedWidth(70)
        layout.addWidget(self.btn)

        self._recording = False

    def value(self) -> str:
        return self.display.text()

    def setValue(self, v: str):
        self.display.setText(v)

    def _on_toggled(self, checked: bool):
        if checked:
            self._recording = True
            self.display.setText("请按下快捷键组合…")
            self.btn.setText("取消")
            self.setFocus()
        else:
            self._recording = False
            self.btn.setText("录制")

    def keyPressEvent(self, event):
        if not self._recording:
            super().keyPressEvent(event)
            return

        key = event.key()
        mod = event.modifiers()

        # Ignore standalone modifier keys
        if key in (
            Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift,
            Qt.Key.Key_Meta, Qt.Key.Key_unknown,
        ):
            return

        parts = []
        if mod & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mod & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mod & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")

        from PyQt6.QtGui import QKeySequence
        key_str = QKeySequence(key).toString().lower()
        if key_str:
            parts.append(key_str)

        combo = "+".join(parts)
        if combo:
            self.display.setText(combo)

        self._recording = False
        self.btn.setChecked(False)
        self.btn.setText("录制")


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._cfg = config
        self.setWindowTitle("AI翻译输入法 — 设置")
        self.setMinimumSize(560, 480)
        self.setStyleSheet(STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_api_tab(), "API 配置")
        self.tabs.addTab(self._build_hotkey_tab(), "热键设置")
        self.tabs.addTab(self._build_lang_tab(), "语言设置")
        self.tabs.addTab(self._build_behavior_tab(), "行为设置")
        self.tabs.addTab(self._build_prompt_tab(), "翻译提示词")
        self.tabs.addTab(self._build_phrases_tab(), "快捷话术")

        # Save / Cancel
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Tab: API
    # ------------------------------------------------------------------
    def _build_api_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(16, 16, 16, 8)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # ── 服务商选择 ──────────────────────────────────────────────────
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(list(PROVIDERS.keys()))
        saved_url = self._cfg.get("api", "base_url", default="https://api.openai.com/v1")
        self.provider_combo.setCurrentText(self._detect_provider(saved_url))
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        form.addRow("服务商:", self.provider_combo)

        # ── API Key ─────────────────────────────────────────────────────
        self.api_key_edit = QLineEdit(self._cfg.get("api", "api_key", default=""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("填写对应服务商的 API Key…")
        form.addRow("API Key:", self.api_key_edit)

        # ── Base URL（可编辑，选服务商后自动填入）──────────────────────
        self.base_url_edit = QLineEdit(saved_url)
        self.base_url_edit.setPlaceholderText("https://…/v1")
        form.addRow("Base URL:", self.base_url_edit)

        url_hint = QLabel("选择服务商后自动填入，也可手动修改（适用于中转/代理地址）。")
        url_hint.setObjectName("hint")
        url_hint.setWordWrap(True)
        form.addRow("", url_hint)

        # ── 模型（可编辑下拉，选服务商后自动刷新列表）──────────────────
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.lineEdit().setPlaceholderText("选择预设模型，或直接输入自定义模型名…")
        self._refresh_model_list(self.provider_combo.currentText(), keep_current=False)
        # 恢复已保存的模型（可能不在列表中，直接设置文本）
        saved_model = self._cfg.get("api", "model", default="gpt-4o-mini")
        idx = self.model_combo.findText(saved_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            self.model_combo.setCurrentText(saved_model)
        form.addRow("模型:", self.model_combo)

        model_hint = QLabel("可从下拉选择常用模型，也可直接输入任意模型名（如 deepseek-r1）。")
        model_hint.setObjectName("hint")
        model_hint.setWordWrap(True)
        form.addRow("", model_hint)

        # ── 代理 ─────────────────────────────────────────────────────────
        self.proxy_edit = QLineEdit(self._cfg.get("api", "proxy", default=""))
        self.proxy_edit.setPlaceholderText("留空=自动读取系统代理；如 http://127.0.0.1:7890")
        form.addRow("代理地址:", self.proxy_edit)

        proxy_hint = QLabel(
            "留空时自动使用 Windows 系统代理（VPN 通常会自动配置）。\n"
            "如需手动指定填写完整地址，如 http://127.0.0.1:7890 。"
        )
        proxy_hint.setObjectName("hint")
        proxy_hint.setWordWrap(True)
        form.addRow("", proxy_hint)

        # ── 超时 ────────────────────────────────────────────────────────
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 120)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setValue(self._cfg.get("api", "timeout", default=30))
        form.addRow("超时时间:", self.timeout_spin)

        # ── 测试连接 ─────────────────────────────────────────────────────
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.setObjectName("secondary")
        self.test_btn.clicked.connect(self._test_connection)
        self.test_result_lbl = QLabel("")
        self.test_result_lbl.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result_lbl, 1)
        form.addRow("", test_row)

        return w

    # ------------------------------------------------------------------
    # Provider helpers
    # ------------------------------------------------------------------
    def _on_provider_changed(self, provider: str):
        preset = PROVIDERS.get(provider, {})
        url = preset.get("base_url", "")
        if url:
            self.base_url_edit.setText(url)
        self._refresh_model_list(provider, keep_current=False)

    def _refresh_model_list(self, provider: str, keep_current: bool = True):
        current_text = self.model_combo.currentText() if keep_current else ""
        self.model_combo.clear()
        models = PROVIDERS.get(provider, {}).get("models", [])
        self.model_combo.addItems(models)
        if keep_current and current_text:
            idx = self.model_combo.findText(current_text)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setCurrentText(current_text)
        elif models:
            self.model_combo.setCurrentIndex(0)

    @staticmethod
    def _detect_provider(base_url: str) -> str:
        """Match a saved base_url back to a known provider name."""
        for name, preset in PROVIDERS.items():
            if name == "自定义":
                continue
            if preset["base_url"] and preset["base_url"].rstrip("/") == base_url.rstrip("/"):
                return name
        return "自定义"

    def _test_connection(self):
        self._apply_api_to_cfg_temporarily()
        translator = Translator(self._cfg)
        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中…")
        self.test_result_lbl.setText("")
        QApplication_processEvents()

        ok, msg = translator.test_connection()
        self.test_btn.setEnabled(True)
        self.test_btn.setText("测试连接")
        color = "#a6e3a1" if ok else "#f38ba8"
        self.test_result_lbl.setStyleSheet(f"color: {color};")
        self.test_result_lbl.setText(msg)

    def _apply_api_to_cfg_temporarily(self):
        """Write current form values to config so translator can use them."""
        self._cfg.set(self.api_key_edit.text().strip(), "api", "api_key")
        self._cfg.set(self.base_url_edit.text().strip(), "api", "base_url")
        self._cfg.set(self.model_combo.currentText().strip(), "api", "model")
        self._cfg.set(self.proxy_edit.text().strip(), "api", "proxy")
        self._cfg.set(self.timeout_spin.value(), "api", "timeout")

    # ------------------------------------------------------------------
    # Tab: Hotkeys
    # ------------------------------------------------------------------
    def _build_hotkey_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(16, 16, 16, 8)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.hotkey_show = HotkeyRecorder(
            self._cfg.get("hotkeys", "show_window", default="ctrl+f1")
        )
        form.addRow("呼出翻译窗口:", self.hotkey_show)

        self.hotkey_clip = HotkeyRecorder(
            self._cfg.get("hotkeys", "translate_clipboard", default="ctrl+f2")
        )
        form.addRow("翻译剪贴板:", self.hotkey_clip)

        hint = QLabel(
            "格式：ctrl+f1 / ctrl+shift+k 等（小写+号分隔）\n"
            "点击「录制」按钮后直接按下想要的组合键。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)

        return w

    # ------------------------------------------------------------------
    # Tab: Language
    # ------------------------------------------------------------------
    def _build_lang_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(16, 16, 16, 8)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        lang_list = list(LANGUAGES.keys())

        self.default_src = QComboBox()
        self.default_src.addItems(lang_list)
        self.default_src.setCurrentText(
            self._cfg.get("languages", "input", default="中文")
        )
        form.addRow("默认源语言:", self.default_src)

        self.default_tgt = QComboBox()
        self.default_tgt.addItems(lang_list)
        self.default_tgt.setCurrentText(
            self._cfg.get("languages", "output", default="英语")
        )
        form.addRow("默认目标语言:", self.default_tgt)

        hint = QLabel("浮窗中可随时临时切换语言，此处仅设置默认值。")
        hint.setObjectName("hint")
        form.addRow("", hint)

        return w

    # ------------------------------------------------------------------
    # Tab: Behavior
    # ------------------------------------------------------------------
    def _build_behavior_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(16, 16, 16, 8)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # ── 自动发送开关 ──────────────────────────────────────────────
        from PyQt6.QtWidgets import QCheckBox
        self.auto_send_check = QCheckBox("粘贴后自动发送消息")
        self.auto_send_check.setChecked(
            self._cfg.get("behavior", "auto_send", default=True)
        )
        self.auto_send_check.toggled.connect(self._on_auto_send_toggled)
        form.addRow("", self.auto_send_check)

        auto_send_hint = QLabel(
            "开启后，翻译内容粘贴到聊天窗口后会自动按下发送键，\n"
            "实现「一键翻译发送」的体验，无需再手动点击发送。"
        )
        auto_send_hint.setObjectName("hint")
        auto_send_hint.setWordWrap(True)
        form.addRow("", auto_send_hint)

        # ── 发送方式 ─────────────────────────────────────────────────
        self.send_key_combo = QComboBox()
        self.send_key_combo.addItems(["Enter", "Ctrl+Enter"])
        saved_key = self._cfg.get("behavior", "send_key", default="enter")
        if saved_key == "ctrl+enter":
            self.send_key_combo.setCurrentIndex(1)
        else:
            self.send_key_combo.setCurrentIndex(0)
        form.addRow("发送方式:", self.send_key_combo)

        send_key_hint = QLabel(
            "大多数聊天软件用 Enter 发送（钉钉、微信、Slack 等）。\n"
            "部分软件可设置为 Ctrl+Enter 发送，请根据实际情况选择。"
        )
        send_key_hint.setObjectName("hint")
        send_key_hint.setWordWrap(True)
        form.addRow("", send_key_hint)

        # 根据开关状态启用/禁用发送方式选择
        self._on_auto_send_toggled(self.auto_send_check.isChecked())

        return w

    def _on_auto_send_toggled(self, checked: bool):
        self.send_key_combo.setEnabled(checked)

    # ------------------------------------------------------------------
    # Tab: Prompt template
    # ------------------------------------------------------------------
    def _build_prompt_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 8)
        layout.setSpacing(8)

        hint = QLabel(
            "可用变量：{input_lang}  {output_lang}  {text}\n"
            "例如加入「请保持商务口吻」以调整翻译风格。"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.prompt_edit = QTextEdit(
            self._cfg.get(
                "prompt_template",
                default="请将以下{input_lang}翻译成{output_lang}，只返回翻译结果，不要解释：\n\n{text}",
            )
        )
        self.prompt_edit.setMinimumHeight(140)
        layout.addWidget(self.prompt_edit)

        reset_btn = QPushButton("恢复默认")
        reset_btn.setObjectName("secondary")
        reset_btn.clicked.connect(self._reset_prompt)
        layout.addWidget(reset_btn, alignment=Qt.AlignmentFlag.AlignRight)

        return w

    def _reset_prompt(self):
        self.prompt_edit.setPlainText(
            "请将以下{input_lang}翻译成{output_lang}，只返回翻译结果，不要解释：\n\n{text}"
        )

    # ------------------------------------------------------------------
    # Tab: Phrases
    # ------------------------------------------------------------------
    def _build_phrases_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 8)
        layout.setSpacing(8)

        hint = QLabel("预存常用话术，在翻译窗口「话术」按钮中一键插入。")
        hint.setObjectName("hint")
        layout.addWidget(hint)

        self.phrase_list = QListWidget()
        for p in self._cfg.get("phrases", default=[]):
            item = QListWidgetItem(f"[{p['name']}]  {p['content'][:40]}…" if len(p['content']) > 40 else f"[{p['name']}]  {p['content']}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.phrase_list.addItem(item)
        layout.addWidget(self.phrase_list)

        btn_row = QHBoxLayout()

        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._add_phrase)
        btn_row.addWidget(add_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.setObjectName("secondary")
        edit_btn.clicked.connect(self._edit_phrase)
        btn_row.addWidget(edit_btn)

        del_btn = QPushButton("删除")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_phrase)
        btn_row.addWidget(del_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        return w

    def _add_phrase(self):
        name, ok = QInputDialog.getText(self, "添加话术", "话术名称（如：催单话术）：")
        if not ok or not name.strip():
            return
        content, ok2 = QInputDialog.getMultiLineText(self, "添加话术", "话术内容：")
        if not ok2 or not content.strip():
            return
        phrase = {"name": name.strip(), "content": content.strip()}
        item = QListWidgetItem(self._phrase_display(phrase))
        item.setData(Qt.ItemDataRole.UserRole, phrase)
        self.phrase_list.addItem(item)

    def _edit_phrase(self):
        row = self.phrase_list.currentRow()
        if row < 0:
            return
        item = self.phrase_list.item(row)
        phrase = item.data(Qt.ItemDataRole.UserRole)

        name, ok = QInputDialog.getText(self, "编辑话术", "话术名称：", text=phrase["name"])
        if not ok:
            return
        content, ok2 = QInputDialog.getMultiLineText(
            self, "编辑话术", "话术内容：", text=phrase["content"]
        )
        if not ok2:
            return
        updated = {"name": name.strip(), "content": content.strip()}
        item.setData(Qt.ItemDataRole.UserRole, updated)
        item.setText(self._phrase_display(updated))

    def _delete_phrase(self):
        row = self.phrase_list.currentRow()
        if row < 0:
            return
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除这条话术吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.phrase_list.takeItem(row)

    @staticmethod
    def _phrase_display(p: dict) -> str:
        preview = p["content"][:40] + "…" if len(p["content"]) > 40 else p["content"]
        return f"[{p['name']}]  {preview}"

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _save(self):
        # API
        self._cfg.set(self.api_key_edit.text().strip(), "api", "api_key")
        self._cfg.set(self.base_url_edit.text().strip(), "api", "base_url")
        self._cfg.set(self.model_combo.currentText().strip(), "api", "model")
        self._cfg.set(self.proxy_edit.text().strip(), "api", "proxy")
        self._cfg.set(self.timeout_spin.value(), "api", "timeout")

        # Hotkeys
        self._cfg.set(self.hotkey_show.value().strip(), "hotkeys", "show_window")
        self._cfg.set(self.hotkey_clip.value().strip(), "hotkeys", "translate_clipboard")

        # Languages
        self._cfg.set(self.default_src.currentText(), "languages", "input")
        self._cfg.set(self.default_tgt.currentText(), "languages", "output")

        # Behavior
        self._cfg.set(self.auto_send_check.isChecked(), "behavior", "auto_send")
        send_key = "enter" if self.send_key_combo.currentIndex() == 0 else "ctrl+enter"
        self._cfg.set(send_key, "behavior", "send_key")

        # Prompt
        self._cfg.set(self.prompt_edit.toPlainText().strip(), "prompt_template")

        # Phrases
        phrases = []
        for i in range(self.phrase_list.count()):
            phrases.append(self.phrase_list.item(i).data(Qt.ItemDataRole.UserRole))
        self._cfg.set(phrases, "phrases")

        self.accept()


# Avoid circular import — QApplication is already running in main.py
def QApplication_processEvents():
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
