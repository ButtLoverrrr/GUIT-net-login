'''验证码识别实现：自研 CRNN（`ocr.OcrBackend` 契约的可插拔后端）。

与 ddddocr 后端的区别
--------------------
ddddocr 直接输出「答案数字」，而本模型是端到端识别**整个算式**（如 `98加5`），
自己求值后再返回数字。对上层完全透明：`classify()` 依旧只返回可直接提交的
答案字符串，业务代码（app / portal_client）一行都不用改。

这个站点验证码的特殊性
--------------------
运算符呈现形式是**固定**的：加法用汉字 `加`、乘法用 `乘`、减法用 `-`、
除法用 `÷`，四者不会互换。因此字符集只需 14 个字符，模型不必区分
「汉字加」和「符号+」。

设计要点（与 ocr_helper 保持一致）
---------------------------------
- 延迟初始化：ONNX 会话首次用到才建，避免拖慢界面出现；
- 失败静默降级：任何异常返回空串，由上层回退手输验证码；
- 线程安全：预取线程与「连接」按钮可能并发调用，加锁避免重复初始化；
- 模型缺失时 available() 为 False，程序自动只用「手输」。

模型文件
--------
默认找 `models/crnn.onnx`（项目根下）。打包后从 `sys._MEIPASS/models/` 取。
路径可用环境变量 `GUIT_CRNN_MODEL` 覆盖，便于临时换模型做 A/B。

切换方式
--------
`config.json` 里把 `options.ocrBackend` 设为 `"crnn"`。
'''

import io
import os
import sys
import threading

from ocr import OcrBackend, register_backend

# 验证码字符集：数字 0-9 + 四种运算符（汉字加/汉字乘/减号/除号）
CHARS = '0123456789加乘-÷'
IMG_W, IMG_H = 200, 64
BLANK = 0

BACKEND_NAME = 'crnn'
MODEL_RELATIVE = os.path.join('models', 'crnn.onnx')


def _model_path() -> str:
    '''定位模型文件：环境变量 > 打包目录 > 项目根。'''

    override = os.environ.get('GUIT_CRNN_MODEL')
    if override:
        return override

    base = getattr(sys, '_MEIPASS', None)
    if base:
        packed = os.path.join(base, MODEL_RELATIVE)
        if os.path.exists(packed):
            return packed

    # src/ocr_crnn.py -> 上一级是项目根
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..', MODEL_RELATIVE))


def solve(text: str):
    '''算式 -> 答案。无法解析或除不尽时返回 None。'''

    import re

    m = re.fullmatch(r'(\d+)([加乘\-÷])(\d+)', text or '')
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    if op == '加':
        v = a + b
    elif op == '-':
        v = a - b
    elif op == '乘':
        v = a * b
    else:
        if b == 0 or a % b:
            return None
        v = a // b
    # 站点输入框 maxlength=4，超长答案必然提交失败，提前判废
    if abs(v) > 9999:
        return None
    return v


class CrnnBackend(OcrBackend):
    '''自研 CRNN 后端：识别算式 -> 求值 -> 返回答案数字。'''

    name = BACKEND_NAME

    def __init__(self, length: int = 4, model_path: str = None):
        self.length = length
        self._model_path = model_path or _model_path()
        self._session = None
        self._input_name = ''
        self._failed = False
        self._lock = threading.Lock()

    # ---------- 契约 ----------

    def available(self) -> bool:
        '''引擎是否可用。模型文件不存在或依赖缺失时为 False。'''

        if self._failed:
            return False
        try:
            import onnxruntime  # noqa: F401
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
        except Exception:
            return False
        return os.path.exists(self._model_path)

    def classify(self, png: bytes) -> str:
        '''识别验证码并返回答案数字字符串；失败返回空串（绝不抛异常）。'''

        try:
            session = self._ensure_session()
            if session is None:
                return ''
            text = self._infer(session, png)
            answer = solve(text)
            return str(answer) if answer is not None else ''
        except Exception:
            return ''

    # ---------- 内部 ----------

    def _ensure_session(self):
        if self._session is not None:
            return self._session
        if not self.available():
            return None
        with self._lock:
            if self._session is not None:
                return self._session
            try:
                import onnxruntime as ort

                opts = ort.SessionOptions()
                opts.log_severity_level = 3          # 只报错，屏蔽 warning
                sess = ort.InferenceSession(
                    self._model_path, opts, providers=['CPUExecutionProvider'])
                self._input_name = sess.get_inputs()[0].name
                self._session = sess
            except Exception:
                self._failed = True
                return None
        return self._session

    def _infer(self, session, png: bytes) -> str:
        import numpy as np
        from PIL import Image

        im = Image.open(io.BytesIO(png)).convert('RGB')
        im = im.resize((IMG_W, IMG_H), Image.Resampling.BICUBIC)
        arr = np.asarray(im).astype(np.float32) / 255.0
        arr = (arr - 0.5) / 0.5
        arr = arr.transpose(2, 0, 1)[None]

        logits = session.run(None, {self._input_name: arr})[0][0]   # (T, C)
        idx = logits.argmax(axis=1).tolist()

        # CTC 贪心解码：去掉 blank 与连续重复
        out, prev = [], BLANK
        for i in idx:
            if i != BLANK and i != prev:
                out.append(CHARS[i - 1])
            prev = i
        return ''.join(out)


register_backend(BACKEND_NAME, lambda length=4: CrnnBackend(length))
