import urllib.request
import requests
from config_manager import ConfigManager, LANGUAGES


class TranslationError(Exception):
    pass


def _get_session() -> requests.Session:
    """Build a requests Session that respects Windows system proxy settings.

    requests reads HTTP_PROXY / HTTPS_PROXY env vars automatically, but on
    Windows those vars are often not set even when a system (browser) proxy
    is active. urllib.request.getproxies() reads the Windows registry and
    returns whatever proxy the browser (and VPN) has configured.
    """
    session = requests.Session()
    system_proxies = urllib.request.getproxies()
    if system_proxies:
        session.proxies.update(system_proxies)
    return session


class Translator:
    """Calls any OpenAI-compatible Chat Completions API to translate text."""

    def __init__(self, config: ConfigManager):
        self._cfg = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """Translate *text* from *src_lang* to *tgt_lang*.

        Both lang params are display names like "中文" / "英语".
        Raises TranslationError on any failure.
        """
        text = text.strip()
        if not text:
            return ""

        api_key = self._cfg.get("api", "api_key", default="")
        base_url = self._cfg.get("api", "base_url", default="https://api.openai.com/v1")
        model = self._cfg.get("api", "model", default="gpt-4o-mini")
        timeout = self._cfg.get("api", "timeout", default=30)
        proxy = self._cfg.get("api", "proxy", default="")
        prompt_tpl = self._cfg.get(
            "prompt_template",
            default="请将以下{input_lang}翻译成{output_lang}，只返回翻译结果，不要解释：\n\n{text}",
        )

        if not api_key:
            raise TranslationError("未配置 API Key，请在设置中填写。")

        prompt = prompt_tpl.format(
            input_lang=src_lang,
            output_lang=tgt_lang,
            text=text,
        )

        url = base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }

        # Proxy priority: manual config > Windows system proxy
        session = _get_session()
        if proxy.strip():
            session.proxies = {"http": proxy.strip(), "https": proxy.strip()}

        try:
            resp = session.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except requests.exceptions.Timeout:
            raise TranslationError(f"请求超时（{timeout}s），请检查网络或增大超时设置。")
        except requests.exceptions.ConnectionError as e:
            raise TranslationError(f"无法连接到 API，请检查 Base URL、网络和代理设置。\n详情: {e}")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            try:
                msg = e.response.json().get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            raise TranslationError(f"API 错误 [{status}]: {msg}")
        except (KeyError, IndexError):
            raise TranslationError("API 返回格式异常，请检查模型名称是否正确。")
        except Exception as e:
            raise TranslationError(f"未知错误: {e}")

    def test_connection(self) -> tuple[bool, str]:
        """Send a minimal request to verify API config.

        Returns (success: bool, message: str).
        """
        try:
            result = self.translate("你好", "中文", "英语")
            return True, f"连接成功！测试翻译结果：{result}"
        except TranslationError as e:
            return False, str(e)

    @staticmethod
    def lang_code(display_name: str) -> str:
        return LANGUAGES.get(display_name, display_name)
