import json
import os
from copy import deepcopy
from pathlib import Path

def get_config_path() -> Path:
    """Get config path in user's AppData folder (writable without admin)."""
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        config_dir = Path(appdata) / "AI翻译输入法"
    else:
        # Fallback to user home directory
        config_dir = Path.home() / ".ai_translator"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"

DEFAULT_CONFIG = {
    "hotkeys": {
        "show_window": "alt+t",
        "translate_clipboard": "alt+c",
    },
    "api": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "timeout": 30,
    },
    "languages": {
        "input": "中文",
        "output": "英语",
    },
    "behavior": {
        "auto_send": True,
        "send_key": "enter",  # "enter" | "ctrl+enter" | "none"
    },
    "prompt_template": (
        "请将以下{input_lang}翻译成{output_lang}，"
        "只返回翻译结果，不要解释：\n\n{text}"
    ),
    "ui": {
        "window_x": -1,
        "window_y": -1,
        "opacity": 0.97,
    },
    "phrases": [
        {"name": "示例：催单话术", "content": "您好，请问您的订单有什么问题需要帮助吗？"},
    ],
}

CONFIG_PATH = get_config_path()

LANGUAGES = {
    "中文": "zh",
    "英语": "en",
    "日语": "ja",
    "韩语": "ko",
    "法语": "fr",
    "德语": "de",
    "西班牙语": "es",
    "葡萄牙语": "pt",
    "俄语": "ru",
    "阿拉伯语": "ar",
    "意大利语": "it",
    "荷兰语": "nl",
    "泰语": "th",
    "越南语": "vi",
    "印尼语": "id",
}


class ConfigManager:
    """Singleton config manager that reads/writes config.json."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = None
        return cls._instance

    def load(self) -> dict:
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._config = self._deep_merge(deepcopy(DEFAULT_CONFIG), loaded)
            except (json.JSONDecodeError, IOError):
                self._config = deepcopy(DEFAULT_CONFIG)
        else:
            self._config = deepcopy(DEFAULT_CONFIG)
        self.save()
        return self._config

    def save(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)

    @property
    def data(self) -> dict:
        if self._config is None:
            self.load()
        return self._config

    def get(self, *keys, default=None):
        val = self.data
        for key in keys:
            if isinstance(val, dict) and key in val:
                val = val[key]
            else:
                return default
        return val

    def set(self, value, *keys):
        cfg = self.data
        for key in keys[:-1]:
            if key not in cfg or not isinstance(cfg[key], dict):
                cfg[key] = {}
            cfg = cfg[key]
        cfg[keys[-1]] = value
        self.save()

    def update_section(self, section: str, data: dict):
        self.data[section] = data
        self.save()

    def _deep_merge(self, base: dict, override: dict) -> dict:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                base[key] = self._deep_merge(base[key], value)
            else:
                base[key] = value
        return base
