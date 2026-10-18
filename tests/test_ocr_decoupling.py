"""OCR 解耦回归测试（对应提交「refactor: OCR 解耦为可插拔接口（src/ocr.py）」）。

覆盖四类「解耦后最容易回退」的问题，全部静态/进程内完成，不联网、不初始化真实引擎：

1. 配置层：`backend_name_of()` 对脏配置（cfg / options / ocrBackend 类型错误）不崩，且
   **不把非法类型静默转成默认 ddddocr**（否则手改配置会意外拉起重量级 OCR）；
2. 装配层：`_LOADERS` 是唯一的惰性加载入口——登记的名字会被真正 import 并自注册；
   模块导入失败 / 未登记的名字一律安全降级为 `NullBackend`；
3. 契约兜底：实现方违反契约抛异常时，`safe_available()` / `safe_classify()` 收敛成
   「不可用 / 空串」，`auto_login()` 因此回退「需要手动输入验证码」而不是崩进程；
4. 打包与工具层：精简重打包清单含 `ocr`，工具脚本不再调用已移除的 `app.OcrEngine`。

测试不依赖真实校园网、系统托盘或 exe。
"""
import ast
import importlib
import os
import sys
import tempfile

import support  # noqa: F401  （与其余测试一致，确保 tests 目录在 sys.path 上）


# --------------------------------------------------------------------- 公共工具

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJ, 'src')
TOOLS = os.path.join(PROJ, 'tools')


def _ocr():
    """取 OCR 接口层模块（测试进程里 src 已在 sys.path 上）。"""

    import ocr
    return ocr


def _snapshot():
    """保存注册表与加载表，用例结束后还原，避免用例间通过全局状态互相污染。"""

    ocr = _ocr()
    return dict(ocr._BACKENDS), dict(ocr._LOADERS), list(sys.path)


def _restore(snap):
    ocr = _ocr()
    backends, loaders, path = snap
    ocr._BACKENDS.clear()
    ocr._BACKENDS.update(backends)
    ocr._LOADERS.clear()
    ocr._LOADERS.update(loaders)
    sys.path[:] = path


# ------------------------------------------------------------------ 1. 配置类型保护

# (配置, 期望后端名, 说明)
BACKEND_NAME_MATRIX = (
    (None, 'crnn', 'cfg 为 None → 按空配置，取默认后端'),
    ({}, 'crnn', '缺 options → 默认后端'),
    ({'options': None}, 'crnn', 'options 为 None → 按空 options'),
    ({'options': []}, 'crnn', 'options 是列表 → 按空 options'),
    ({'options': 'bad'}, 'crnn', 'options 是字符串 → 按空 options'),
    ({'options': {'ocrBackend': None}}, 'crnn', '值缺失/None → 默认后端'),
    ({'options': {'ocrBackend': ''}}, 'crnn', '空串 → 视为未配置，取默认'),
    ({'options': {'ocrBackend': '   '}}, 'crnn', '纯空白 → 视为未配置，取默认'),
    ({'options': {'ocrBackend': 123}}, 'none', '值是数字 → 非法配置按 none（不启重引擎）'),
    ({'options': {'ocrBackend': ['ddddocr']}}, 'none', '值是列表 → 非法配置按 none'),
    ({'options': {'ocrBackend': {'name': 'ddddocr'}}}, 'none', '值是对象 → 非法配置按 none'),
    ({'options': {'ocrBackend': 'unknown'}}, 'unknown', '未知字符串照样透传（由装配处降级）'),
    ({'options': {'ocrBackend': ' crnn '}}, 'crnn', '两端空白要 strip'),
    ({'options': {'useOcr': False, 'ocrBackend': 'crnn'}}, 'none', 'useOcr=False 一律等价 none'),
    ({'options': {'useOcr': True, 'ocrBackend': 'none'}}, 'none', 'useOcr=True + none → none'),
    ({'options': {'useOcr': True}}, 'crnn', 'useOcr 缺失/True → 默认启用'),
)


def test_backend_name_of_type_safety_matrix():
    """配置矩阵：脏类型不崩、语义明确（见表内期望值）。"""

    ocr = _ocr()
    for cfg, expected, why in BACKEND_NAME_MATRIX:
        got = ocr.backend_name_of(cfg)
        assert got == expected, f'{cfg!r} 期望 {expected!r}，实际 {got!r}（{why}）'


def test_backend_name_of_never_raises_on_hostile_config():
    """任何形状的配置都不能让启动路径抛异常（配置可被手工编辑）。"""

    ocr = _ocr()

    class Boom:
        def get(self, *_a, **_k):
            raise RuntimeError('配置对象本身就有问题')

    for cfg in ([], 'x', 0, Boom(), {'options': Boom()}, {'options': {'ocrBackend': Boom()}}):
        try:
            got = ocr.backend_name_of(cfg)
        except Exception as exc:            # noqa: BLE001 断言用：不允许任何异常逃逸
            raise AssertionError(f'{cfg!r} 不得抛异常，实际 {type(exc).__name__}: {exc}')
        assert isinstance(got, str) and got, f'{cfg!r} 必须返回非空字符串，实际 {got!r}'


def test_create_engine_for_dirty_config_never_initializes_default_backend():
    """非法 `ocrBackend` 值一律落回 none：手工写错类型不能触发 ddddocr 初始化。

    只覆盖**类型非法**的值（数字 / 列表 / 对象）——它们由 `backend_name_of()` 直接
    判为 none。以下情况**不在**本例内，因为它们本来就该取默认后端，调用默认工厂是
    正确行为（另有断言覆盖）：
    - `ocrBackend` 缺失或为 None：等于「键未配置」；
    - `cfg` / `options` 本身类型不对：按空配置处理，自然取默认后端。
    """

    ocr = _ocr()
    snap = _snapshot()
    try:
        calls = []

        def spy(length=4):
            calls.append(length)
            raise AssertionError('非法 ocrBackend 不应装配默认后端')

        ocr.register_backend('ddddocr', spy, replace=True)
        for cfg in (
            {'options': {'ocrBackend': 123}},
            {'options': {'ocrBackend': ['ddddocr']}},
            {'options': {'ocrBackend': {'name': 'ddddocr'}}},
            {'options': {'ocrBackend': 1.5}},
            {'options': {'ocrBackend': True}},
        ):
            eng = ocr.create_engine(cfg)
            assert isinstance(eng, ocr.NullBackend), (cfg, type(eng))
        assert calls == [], f'非法配置不得触碰默认后端工厂：{calls}'
    finally:
        _restore(snap)


def test_default_backend_still_selected_when_config_is_silent():
    """反向护栏：配置没提 OCR 时仍要装配默认后端（别把类型保护做成「谁都不用」）。"""

    ocr = _ocr()
    snap = _snapshot()
    try:
        calls = []

        class _Default:
            name = 'crnn'

            def __init__(self, length=4):
                self.CAPTCHA_LENGTH = length

            def available(self):
                return True

            def classify(self, png):
                return 'ok'

        ocr.register_backend('crnn', (lambda length=4: (calls.append(length), _Default(length))[1]),
                             replace=True)
        for cfg in ({}, None, {'options': None}, {'options': {}},
                    {'options': {'ocrBackend': None}}, {'options': {'ocrBackend': '   '}},
                    {'options': 'bad'}, {'options': {'useOcr': True}}):
            eng = ocr.create_engine(cfg)
            assert isinstance(eng, _Default), (cfg, type(eng))
            assert eng.name == 'crnn' and eng.available() is True, cfg
        assert len(calls) == 8, f'每个缺省配置都应装配一次默认后端：{calls}'
    finally:
        _restore(snap)


# ---------------------------------------------------------------- 2. 自定义后端加载


def test_loader_table_registers_module_and_loads_on_demand():
    """`_LOADERS` 登记的名字必须被真正 import，并由模块在导入时自注册。"""

    ocr = _ocr()
    snap = _snapshot()
    tmpdir = tempfile.mkdtemp(prefix='guit-ocr-loader-')
    module_name = 'guit_custom_ocr_probe'
    path = os.path.join(tmpdir, module_name + '.py')
    with open(path, 'w', encoding='utf-8') as fp:
        fp.write(
            'from ocr import OcrBackend, register_backend\n'
            '\n'
            'class ProbeBackend(OcrBackend):\n'
            "    name = 'probe'\n"
            '\n'
            '    def __init__(self, length=4):\n'
            '        self.CAPTCHA_LENGTH = length\n'
            '\n'
            '    def available(self):\n'
            '        return True\n'
            '\n'
            '    def classify(self, png):\n'
            "        return 'ab12'[:self.CAPTCHA_LENGTH]\n"
            '\n'
            "register_backend('probe', lambda length=4: ProbeBackend(length))\n"
        )
    sys.path.insert(0, tmpdir)
    try:
        ocr._BACKENDS.pop('probe', None)
        ocr._LOADERS['probe'] = module_name
        try:
            eng = ocr.create_backend('probe', 2)
        except Exception as exc:            # noqa: BLE001 断言用
            raise AssertionError(f'create_backend 不应抛异常：{type(exc).__name__}: {exc}')
        assert not isinstance(eng, ocr.NullBackend), '登记的模块必须被导入并注册出真实后端'
        assert type(eng).__name__ == 'ProbeBackend', type(eng).__name__
        assert eng.CAPTCHA_LENGTH == 2, 'length 必须透传给工厂'
        assert eng.available() is True and eng.classify(b'\x89PNG') == 'ab', eng
        assert module_name in sys.modules, '登记后必须 import 对应模块'
    finally:
        sys.modules.pop(module_name, None)
        _restore(snap)


def test_unregistered_backend_name_never_imports_anything():
    """未在 `_LOADERS` 登记的名字：不扫描目录、不猜模块名，直接降级为 none。"""

    ocr = _ocr()
    snap = _snapshot()
    try:
        eng = ocr.create_backend('definitely-not-registered')
        assert isinstance(eng, ocr.NullBackend), type(eng)
        assert not any(k.split('.')[-1] == 'definitely-not-registered' for k in sys.modules)
    finally:
        _restore(snap)


def test_loader_import_failure_degrades_to_null():
    """登记的模块导入失败（精简构建去掉实现）→ 降级 none，不抛异常。"""

    ocr = _ocr()
    snap = _snapshot()
    try:
        ocr._LOADERS['ghost'] = 'ghost_module_that_does_not_exist'
        eng = ocr.create_backend('ghost')
        assert isinstance(eng, ocr.NullBackend), type(eng)
        assert eng.available() is False and eng.classify(b'\x89PNG') == ''
    finally:
        _restore(snap)


def test_broken_backend_module_degrades_instead_of_crashing():
    """模块能 import 但自身抛错 / 未注册 / 工厂炸：全部收敛成 none。"""

    ocr = _ocr()
    snap = _snapshot()
    tmpdir = tempfile.mkdtemp(prefix='guit-ocr-broken-')
    cases = {
        'guit_broken_raises': 'raise RuntimeError("模块导入就炸")\n',
        'guit_broken_silent': '# 导入了但什么都没注册\n',
        'guit_broken_factory': (
            'from ocr import register_backend\n'
            'def _factory(length=4):\n'
            '    raise RuntimeError("工厂炸")\n'
            "register_backend('broken', _factory)\n"
        ),
    }
    for name, body in cases.items():
        with open(os.path.join(tmpdir, name + '.py'), 'w', encoding='utf-8') as fp:
            fp.write(body)
    sys.path.insert(0, tmpdir)
    try:
        for name in cases:
            ocr._BACKENDS.pop(name, None)
            ocr._LOADERS[name] = name
            eng = ocr.create_backend(name)
            assert isinstance(eng, ocr.NullBackend), (name, type(eng))
    finally:
        for name in cases:
            sys.modules.pop(name, None)
        _restore(snap)


def test_available_backends_lists_null_default_and_loaders():
    """后端清单至少包含 none / ddddocr，且随登记变化。"""

    ocr = _ocr()
    snap = _snapshot()
    try:
        names = ocr.available_backends()
        assert 'none' in names and 'ddddocr' in names, names
        ocr._LOADERS['probe-list'] = 'guit_probe_list'
        assert 'probe-list' in ocr.available_backends()
    finally:
        _restore(snap)


# ------------------------------------------------------------------ 3. 契约兜底


class _BoomBackend:
    """违反契约的实现：两个方法都抛异常（第三方实现的典型故障）。"""

    name = 'boom'

    def available(self):
        raise RuntimeError('模型文件损坏')

    def classify(self, png):
        raise RuntimeError('onnxruntime 版本不匹配')


class _WrongTypeBackend:
    name = 'wrong-type'

    def available(self):
        return True

    def classify(self, png):
        return None            # 契约要求返回 str


class _ClassifyBoomBackend:
    """可用但识别时抛异常：必须走「回退手输」，不能把异常漏给调用方。"""

    name = 'classify-boom'

    def available(self):
        return True

    def classify(self, png):
        raise RuntimeError('识别阶段炸了')


def test_safe_wrappers_absorb_contract_violations():
    """safe_available / safe_classify：异常与错类型都收敛，不向外抛。"""

    ocr = _ocr()
    assert ocr.safe_available(None) is False
    assert ocr.safe_classify(None, b'x') == ''
    assert ocr.safe_available(_BoomBackend()) is False, 'available 抛异常 → False'
    assert ocr.safe_classify(_BoomBackend(), b'\x89PNG') == '', 'classify 抛异常 → 空串'
    assert ocr.safe_available(_WrongTypeBackend()) is True
    assert ocr.safe_classify(_WrongTypeBackend(), b'\x89PNG') == '', '非 str 返回值 → 空串'


def test_lifecycle_wrappers_never_leak_exceptions_from_backends():
    """收尾路径（auto_login）对坏后端必须是「回退手输」，不是崩溃、也不是网络错误。"""

    pc, cfg, portal = _login_env()
    try:
        portal.state.online = False
        for backend in (_BoomBackend(), _ClassifyBoomBackend()):
            log = []
            r = pc.auto_login(cfg, _Logger(log), ocr=backend)
            assert r.ok is False, (backend.name, r)
            assert r.kind == pc.KIND_NEED_MANUAL, (backend.name, r.kind, r.message)
            assert r.kind != pc.KIND_NETWORK, 'OCR 故障不得被误报成网络错误'
            assert '手动' in r.message, (backend.name, r.message)
            assert '内部错误' not in r.message, r.message
    finally:
        portal.stop()


def test_gui_use_ocr_falls_back_when_backend_raises():
    """GUI 的 `_use_ocr()` 走 safe_available：坏后端等价于「OCR 不可用」。"""

    import app as appmod
    from tkinter import Tk
    root = Tk()
    root.withdraw()
    try:
        ui = appmod.LoginApp.__new__(appmod.LoginApp)      # 不建窗口，只测判定函数
        ui.cfg = {'options': {'useOcr': True}}
        ui.ocr = _BoomBackend()
        assert ui._use_ocr() is False, '后端抛异常时必须判为不可用（回退手输）'
        ui.cfg = {'options': {'useOcr': False}}
        ui.ocr = _WrongTypeBackend()
        assert ui._use_ocr() is False, '历史开关关闭时不得调用后端'
    finally:
        root.destroy()


# ------------------------------------------------------- 4. 打包清单与工具迁移


def _module_names(path):
    """静态读出某个 Python 文件里的模块名清单常量（不执行代码）。"""

    tree = ast.parse(open(path, encoding='utf-8').read(), filename=path)
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and isinstance(node.value, (ast.Tuple, ast.List)):
                try:
                    found[target.id] = list(ast.literal_eval(node.value))
                except (ValueError, SyntaxError):
                    continue
    return found


def test_slim_repack_module_list_includes_ocr():
    """精简重打包必须重编译 src/ocr.py：漏了它产物 import ocr 直接失败。"""

    path = os.path.join(TOOLS, 'build_slim_exe.py')
    names = _module_names(path)
    pyz = names.get('PYZ_MODULES')
    assert pyz is not None, 'build_slim_exe.py 里找不到 PYZ_MODULES'
    assert 'ocr' in pyz, f'PYZ_MODULES 必须含接口层 ocr：{pyz}'
    assert 'ocr_helper' in pyz, '默认实现 ocr_helper 不能被删除'
    assert 'ocr_crnn' in pyz, '登录页 CRNN 后端 ocr_crnn 必须在 PYZ_MODULES（否则改了源码不生效）'
    for mod in pyz:
        src_file = os.path.join(SRC, mod + '.py')
        assert os.path.isfile(src_file), f'PYZ_MODULES 里的 {mod} 没有对应源码：{src_file}'


def test_analyze_module_list_includes_ocr():
    """结构分析工具必须把接口层纳入清单，否则调用链报告仍停在解耦前。"""

    names = _module_names(os.path.join(TOOLS, 'analyze.py'))
    mods = names.get('MODULES')
    assert mods is not None, 'analyze.py 里找不到 MODULES'
    assert 'ocr' in mods and 'ocr_helper' in mods, mods


def test_no_tool_depends_on_the_removed_app_ocr_engine():
    """OCR 解耦后 app 不再导出 OcrEngine；任何当前工具都不得调用它。"""

    offenders = []
    for name in sorted(os.listdir(TOOLS)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(TOOLS, name)
        text = open(path, encoding='utf-8').read()
        tree = ast.parse(text, filename=path)
        for node in ast.walk(tree):
            # 只认属性访问形式：appmod.OcrEngine / app.OcrEngine / appmod.OcrEngine(...)
            if isinstance(node, ast.Attribute) and node.attr == 'OcrEngine':
                base = node.value
                base_name = getattr(base, 'id', None) or getattr(base, 'attr', None)
                if base_name in ('app', 'appmod', 'app_module'):
                    offenders.append(f'{name}:{node.lineno}')
        if 'from app import OcrEngine' in text:
            offenders.append(f'{name}: from app import OcrEngine')
    assert not offenders, f'工具仍在调用已移除的 app.OcrEngine：{offenders}'


def test_app_exports_only_ocr_contract_assembly():
    """app 的装配入口按契约返回 OcrBackend，且默认实现是 ddddocr。"""

    import app as appmod
    ocr = _ocr()
    none_eng = appmod.build_ocr_engine({'options': {'ocrBackend': 'none'}})
    assert isinstance(none_eng, ocr.NullBackend) and none_eng.available() is False
    default_eng = appmod.build_ocr_engine({'options': {}})
    assert isinstance(default_eng, ocr.OcrBackend)
    assert default_eng.name == 'crnn'
    assert not hasattr(appmod, 'OcrEngine'), 'app 不应再导出 OcrEngine（已迁移到 ocr_helper）'


def test_tools_no_longer_reference_removed_app_export():
    """工具里对 OCR 的引用要么走 build_ocr_engine，要么是默认实现专项。"""

    allowed_default_only = {'race_ocr.py', 'fidelity.py'}
    problems = []
    for name in sorted(os.listdir(TOOLS)):
        if not name.endswith('.py') or name in allowed_default_only:
            continue
        text = open(os.path.join(TOOLS, name), encoding='utf-8').read()
        if 'ocr_helper.OcrEngine' in text and 'build_ocr_engine' not in text:
            problems.append(name)
    assert not problems, f'这些工具还在直接构造默认实现：{problems}'


# ------------------------------------------------------------------ 共用小工具


class _Logger:
    def __init__(self, sink):
        self.lines = sink

    def _add(self, msg):
        if isinstance(self.lines, list):
            self.lines.append(msg)

    def info(self, m):
        self._add(m)

    def warn(self, m):
        self._add(m)

    def error(self, m):
        self._add(m)

    def set_sink(self, s):
        pass


def _login_env():
    """沙箱 + 模拟门户 + 一份可用配置（与其余测试同一套支撑）。"""

    sb = support.Sandbox(tempfile.mkdtemp(prefix='guit-ocr-dec-'))
    sb.install()
    portal = support.MockPortal()
    return portal_client_module(), portal.config(), portal


def portal_client_module():
    """延迟导入 portal_client（沙箱 install() 之后调用，保证拿到打过桩的模块）。"""

    return importlib.import_module('portal_client')
