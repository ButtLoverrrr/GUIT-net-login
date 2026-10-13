# -*- coding: utf-8 -*-
"""验证码识别封装（ddddocr，MIT）。

设计要点：
- 延迟初始化：ddddocr 首次加载 onnx 模型需要约 1~2 秒，且只有「连接」时才用到，
  因此不在启动时构造，避免拖慢界面出现速度；
- 失败静默降级：任何异常都返回空串，由上层回退到手输验证码，不影响主流程；
- lite 构建（不含 ddddocr）时 available() 恒为 False，程序自动只用「手输」。
"""


class OcrEngine:
    """ddddocr 的薄封装：可用时返回 4 位识别结果，不可用返回空串。"""

    CAPTCHA_LENGTH = 4

    def __init__(self, length: int = 4):
        self.CAPTCHA_LENGTH = length
        self._engine = None
        self._initialized = False

    def available(self) -> bool:
        """惰性初始化并返回是否可用。"""
        if not self._initialized:
            self._initialized = True
            try:
                import ddddocr  # 延迟导入，lite 构建下不存在

                self._engine = ddddocr.DdddOcr(show_ad=False)
            except Exception:
                self._engine = None
        return self._engine is not None

    def classify(self, png_bytes: bytes) -> str:
        """识别验证码；失败或无引擎时返回空串。"""
        if not png_bytes or not self.available():
            return ""
        try:
            raw = self._engine.classification(png_bytes)
        except Exception:
            return ""
        text = "".join(ch for ch in str(raw) if ch.isalnum())
        return text[: self.CAPTCHA_LENGTH]
