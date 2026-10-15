'''OCR 接口层：业务代码只依赖这里的契约，具体识别实现按名字装配。

为什么要这层
------------
界面（`app.py`）与登录流程（`portal_client.auto_login`）只需要两件事——「引擎可用吗」
和「识别这张验证码」。它们不应该知道背后是 ddddocr、自研 ONNX，还是根本没有 OCR。
本模块把这两件事定成契约（`OcrBackend`），实现通过注册表按名字装配：

    options.ocrBackend = "ddddocr"（默认） | "none"（显式关闭） | 任何已登记的名字

契约
----
    available() -> bool           引擎是否可用；False 时调用方回退到「手动输入验证码」
    classify(png: bytes) -> str   识别验证码；失败返回空串，绝不抛异常

调用方还应使用 `safe_available()` / `safe_classify()`：实现方违反契约抛异常时，
它们把它收敛成「不可用 / 空串」，不打断主流程、也不误报成网络错误。

内置实现
--------
    ddddocr  来自 `ocr_helper`（惰性导入，模块导入时不碰 ddddocr）
    none     `NullBackend`：永远不可用，等价于「只用手动输入」

接入自己的实现（`_LOADERS` 是唯一的惰性加载入口）
------------------------------------------------
1) 新写一个模块（例如 `src/my_ocr.py`），实现 `OcrBackend` 的两个方法；
2) 模块**导入时**注册：`ocr.register_backend('my', lambda length=4: MyBackend(length))`；
3) 在本模块的 `_LOADERS` 里登记 `'my': 'my_ocr'`——**必须同时登记**，
   否则 `create_backend('my')` 找不到实现，只会安全降级成 `none`；
4) `config.json` 里把 `options.ocrBackend` 设为 `"my"`。

打包注意
--------
实现模块是**惰性导入**的（见 `_LOADERS`），PyInstaller 的静态分析看不到它，
因此 `scripts/build.ps1` 必须保留 `--hidden-import ocr_helper`（自定义实现同理要加）；
`scripts/check_bundle.py` 也有对应断言，漏收会在构建阶段直接失败。
`--hidden-import` 只负责把模块打进包，**不负责运行时自动导入**：真正触发导入的
永远是 `_LOADERS` 登记 + `create_backend()` 的惰性导入。

（接口约定与打包约束的完整说明见 `docs/ocr-interface.md`。）
'''

import abc
import importlib

DEFAULT_BACKEND = 'ddddocr'
NULL_BACKEND = 'none'

# 名字 → 提供该实现的模块名（首次用到时惰性导入；模块导入时自行注册）。
# 这是**唯一的惰性加载入口**：不在表里的名字不会去 import 任何模块。
# 自定义实现必须在这里登记（hidden-import 只解决「打进包」，不解决「加载」）。
_LOADERS = {
    'ddddocr': 'ocr_helper',
}

# 名字 → 工厂：factory(length) -> OcrBackend
_BACKENDS = {}


class OcrBackend(abc.ABC):
    '''识别引擎契约。业务代码只依赖本类定义的两个方法。'''

    name = 'abstract'

    @abc.abstractmethod
    def available(self) -> bool:
        '''引擎是否可用（不可用则调用方回退手动输入）。'''
        raise NotImplementedError

    @abc.abstractmethod
    def classify(self, png: bytes) -> str:
        '''识别验证码；失败返回空串（不抛异常）。'''
        raise NotImplementedError


class NullBackend(OcrBackend):
    '''显式关闭 OCR：永远不可用，识别恒为空串。'''

    name = NULL_BACKEND

    def available(self) -> bool:
        return False

    def classify(self, png: bytes) -> str:
        return ''


def register_backend(name: str, factory, replace: bool = False) -> None:
    '''注册一个实现。factory(length) 返回 OcrBackend 实例。'''

    if not name:
        raise ValueError('后端名字不能为空')
    if name in _BACKENDS and not replace:
        raise ValueError('后端已注册：%s（需要覆盖请传 replace=True）' % name)
    _BACKENDS[name] = factory


def available_backends() -> tuple:
    '''已知的后端名字（含尚未导入实现模块的）。'''

    return tuple(sorted(set(_BACKENDS) | set(_LOADERS) | {NULL_BACKEND}))


def _import_loader(module_name: str) -> bool:
    '''按 `_LOADERS` 登记的名字导入实现模块（成功返回 True）。

    契约：实现模块在**导入时**调用 `register_backend()` 自注册。导入失败
    （精简构建去掉了该模块、模块自身抛错）一律返回 False，由调用方降级成
    `NullBackend`——查询后端可用性不该打断登录主流程。

    这里只捕获该模块导入本身的失败：导入成功后 `create_backend()` 里构造
    实例的异常另有兜底。
    '''

    try:
        importlib.import_module(module_name)
        return True
    except Exception:                   # noqa: BLE001 见上面说明：仅覆盖导入阶段
        return False


def create_backend(name: str = None, length: int = 4) -> OcrBackend:
    '''按名字装配一个后端实例。

    - 已注册 → 直接构造；
    - 在 `_LOADERS` 里 → 惰性导入实现模块（导入时自注册）后构造；
    - 未知名字 → 返回 `NullBackend`（安全降级为手动输入，不抛异常打断主流程）。
    '''

    if not isinstance(name, str):
        # 配置被手改成脏类型（数字 / 字典）：不能崩，也不能擅自按名字去 import。
        name = ''
    name = (name or DEFAULT_BACKEND).strip() or DEFAULT_BACKEND
    if name == NULL_BACKEND:
        return NullBackend()
    if name not in _BACKENDS:
        module = _LOADERS.get(name)
        if module:
            _import_loader(module)
    factory = _BACKENDS.get(name)
    if factory is None:
        return NullBackend()
    try:
        return factory(length)
    except Exception:
        return NullBackend()


def backend_name_of(cfg: dict = None) -> str:
    '''从配置里取后端名：`options.ocrBackend`，缺省为 ddddocr。

    类型保护（配置可被手工编辑，任何脏值都不得让程序启动崩溃）：
    - `cfg` 不是 dict → 按空配置处理；
    - `options` 不是 dict → 按空 options 处理；
    - `ocrBackend` 值不是字符串（数字 / 字典 / 列表等）→ 返回 `none`：
      非法配置**不**回退到默认 ddddocr，避免手改错类型时意外拉起重量级 OCR；
    - `ocrBackend` 是空串 / 纯空白 → 视为未配置，取默认 `ddddocr`。

    `options.useOcr` 为 False 时一律当作 none（历史开关，语义等价；缺失默认启用）。
    '''

    options = cfg.get('options') if isinstance(cfg, dict) else None
    if not isinstance(options, dict):
        options = {}
    if not bool(options.get('useOcr', True)):
        return NULL_BACKEND
    name = options.get('ocrBackend')
    if name is None:
        return DEFAULT_BACKEND
    if not isinstance(name, str):
        return NULL_BACKEND
    return name.strip() or DEFAULT_BACKEND


def create_engine(cfg: dict = None, length: int = 4) -> OcrBackend:
    '''按配置装配识别引擎（业务代码用这一个入口，不关心具体实现）。'''

    return create_backend(backend_name_of(cfg), length)


# ---------------------------------------------------------------------- 契约兜底
# `OcrBackend` 要求实现方「不抛异常」，但第三方实现未必守约（模型文件损坏、
# onnxruntime 版本不匹配、自定义实现的 bug…）。调用方一旦被异常打断，静默模式会
# 直接崩进程、GUI 会把 OCR 故障报成「内部错误」。因此调用点统一走下面两个包装：
# 契约被违反时收敛成「不可用」或「空串」，由现有「手动输入验证码」流程接管。

def safe_available(backend=None) -> bool:
    '''`backend.available()` 的安全版本：异常或缺少方法都按「不可用」处理。'''

    if backend is None:
        return False
    try:
        return bool(backend.available())
    except Exception:
        return False


def safe_classify(backend, png: bytes) -> str:
    '''`backend.classify()` 的安全版本：异常时返回空串（上层回退手输）。

    返回值同样收敛成 str：实现方返回 None / bytes 时不能让界面上出现
    「None」这种字面量。
    '''

    if backend is None:
        return ''
    try:
        result = backend.classify(png)
    except Exception:
        return ''
    if not isinstance(result, str):
        return ''
    return result
