'''验证码识别封装（ddddocr，MIT）。

设计要点：
- 延迟初始化：ddddocr 首次加载 onnx 模型需要约 1~2 秒，且只有「连接」时才用到，
  因此不在启动时构造，避免拖慢界面出现速度；
- 失败静默降级：任何异常都返回空串，由上层回退到手输验证码，不影响主流程；
- lite 构建（不含 ddddocr）时 available() 恒为 False，程序自动只用「手输」；
- 线程安全：预取线程可能正在加载引擎，而用户此时点了「连接」（另一个线程）——
  旧写法先把 _initialized 置 True 再初始化，第二个线程会读到"已初始化但没有引擎"
  从而误判「OCR 不可用」并要求手输验证码（实测复现：[False, True]）。加锁后
  并发调用会等第一个线程出结果。
'''

import sys
import threading
import types

_CV2_SHIM_DONE = False


def _ensure_cv2_shim() -> None:
    '''精简构建里不含 OpenCV 时，给 ddddocr 装一个「按需报错」的 cv2 兼容桩。

    为什么可以这样做：ddddocr 顶层会 `import cv2`，把 82 MB 的 OpenCV 拖进发行包；
    但 cv2 只被 ddddocr 的 **目标检测（DetectionEngine）/ 滑块匹配（SlideEngine）/
    颜色过滤（ColorFilter）** 子模块使用，而本程序唯一走的路径是
    `DdddOcr(show_ad=False)` + `classification()`（`color_filter` 默认 False）。
    实测（陷阱 cv2 替换真 cv2）：import ddddocr、构造引擎、连续 classify 全程
    **零 cv2 属性访问**。因此精简构建用桩替代，体积省下约 29 MiB（原包的 36%）；
    若环境里存在真 cv2，则直接用真件（完整构建行为不变）。
    桩只在真的用到 cv2 功能时才抛错，避免"静默算错"。
    '''

    global _CV2_SHIM_DONE
    existing = sys.modules.get('cv2')
    if _CV2_SHIM_DONE or existing is not None:
        return
    try:
        import cv2                                   # noqa: F401
        _CV2_SHIM_DONE = True
        return
    except ImportError:
        pass
    stub = types.ModuleType('cv2')
    stub.__version__ = 'not-bundled'

    def _unavailable(name: str):
        raise RuntimeError(
            'cv2.%s 不可用：本构建未包含 OpenCV（程序不需要图像预处理/滑块/目标检测）。'
            '如确需，请使用完整构建。' % name)

    stub.__getattr__ = _unavailable                  # type: ignore[attr-defined]
    sys.modules['cv2'] = stub
    _CV2_SHIM_DONE = True


class OcrEngine:
    '''ddddocr 的薄封装：可用时返回 4 位识别结果，不可用返回空串。'''

    CAPTCHA_LENGTH = 4
    def __init__(self, length: int=4):
        self.CAPTCHA_LENGTH = length
        self._engine = None
        self._initialized = False
        self._lock = threading.Lock()

    def available(self) -> bool:
        '''惰性初始化并返回是否可用（多线程安全）。'''

        if self._engine is not None:
            return True
        with self._lock:
            if not self._initialized:
                self._initialized = True
                try:
                    _ensure_cv2_shim()
                    import ddddocr
                    self._engine = ddddocr.DdddOcr(show_ad=False)
                except Exception:
                    self._engine = None
        return self._engine is not None

    def classify(self, png_bytes: bytes) -> str:
        '''识别验证码；失败或无引擎时返回空串。'''

        if not png_bytes or not self.available():
            return ''
        try:
            raw = self._engine.classification(png_bytes)
        except Exception:
            return ''
        # ddddocr 返回的可能是非 str（None / bytes 之外的实现差异），str() 兜底；
        # 取长度用实例上的 CAPTCHA_LENGTH（构造参数会覆盖类常量）。
        text = ''.join((ch for ch in str(raw) if ch.isalnum()))
        return text[:self.CAPTCHA_LENGTH]
