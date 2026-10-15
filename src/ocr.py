'''OCR 接口层：业务代码只依赖这里的契约，具体识别实现按名字装配。

为什么要这层
------------
界面（`app.py`）与登录流程（`portal_client.auto_login`）只需要两件事——「引擎可用吗」
和「识别这张验证码」。它们不应该知道背后是 ddddocr、自研 ONNX，还是根本没有 OCR。
本模块把这两件事定成契约（`OcrBackend`），实现通过注册表按名字装配：

    options.ocrBackend = "ddddocr"（默认） | "none"（显式关闭） | 任何已注册的名字

契约
----
    available() -> bool           引擎是否可用；False 时调用方回退到「手动输入验证码」
    classify(png: bytes) -> str   识别验证码；失败返回空串，绝不抛异常

内置实现
--------
    ddddocr  来自 `ocr_helper`（惰性导入，模块导入时不碰 ddddocr）
    none     `NullBackend`：永远不可用，等价于「只用手动输入」

接入自己的实现
--------------
1) 新写一个模块（例如 `my_ocr.py`），实现 `OcrBackend` 的两个方法；
2) 模块导入时注册：`ocr.register_backend('my', lambda length=4: MyBackend(length))`；
3) `config.json` 里把 `options.ocrBackend` 设为 `"my"`。

打包注意
--------
实现模块是**惰性导入**的（见 `_LOADERS`），PyInstaller 的静态分析看不到它，
因此 `scripts/build.ps1` 必须保留 `--hidden-import ocr_helper`；
`scripts/check_bundle.py` 也有对应断言，漏收会在构建阶段直接失败。

（接口约定与打包约束的完整说明见 `docs/ocr-interface.md`。）
'''

import abc
import importlib

DEFAULT_BACKEND = 'ddddocr'
NULL_BACKEND = 'none'

# 名字 → 提供该实现的模块名（首次用到时惰性导入；模块导入时自行注册）
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


def create_backend(name: str = None, length: int = 4) -> OcrBackend:
    '''按名字装配一个后端实例。

    - 已注册 → 直接构造；
    - 在 `_LOADERS` 里 → 惰性导入实现模块（导入时自注册）后构造；
    - 未知名字 → 返回 `NullBackend`（安全降级为手动输入，不抛异常打断主流程）。
    '''

    name = (name or DEFAULT_BACKEND).strip()
    if name == NULL_BACKEND:
        return NullBackend()
    if name not in _BACKENDS:
        module = _LOADERS.get(name)
        if module:
            try:
                importlib.import_module(module)
            except Exception:
                pass  # 实现模块不可用（例如精简构建去掉了 OCR）→ 走下面的降级
    factory = _BACKENDS.get(name)
    if factory is None:
        return NullBackend()
    try:
        return factory(length)
    except Exception:
        return NullBackend()


def backend_name_of(cfg: dict = None) -> str:
    '''从配置里取后端名：`options.ocrBackend`，缺省为 ddddocr。

    `options.useOcr` 为 False 时一律当作 none（历史开关，语义等价）。
    '''

    options = (cfg or {}).get('options') or {}
    if not bool(options.get('useOcr', True)):
        return NULL_BACKEND
    name = options.get('ocrBackend')
    return (name or DEFAULT_BACKEND).strip() or DEFAULT_BACKEND


def create_engine(cfg: dict = None, length: int = 4) -> OcrBackend:
    '''按配置装配识别引擎（业务代码用这一个入口，不关心具体实现）。'''

    return create_backend(backend_name_of(cfg), length)
