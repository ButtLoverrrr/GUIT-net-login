# coding=utf-8
"""PyInstaller 打包清单检查器（只读，标准库）。

用途
----
在隔离构建后校验 full / lite 两种目标「收进了什么」，用于确认体积压缩阶段 A 的
收集规则真正生效；也可对历史/备份清单做离线回归校验。

覆盖三层清单
------------
- ``PKG-00.toc``   ：最终打进 exe 归档的文件条目（DATA / BINARY / EXTENSION / PYSOURCE...）。
- ``PYZ-00.toc``   ：PYZ 归档内的模块清单（点分模块名）。
- ``Analysis-00.toc``（可选）：hiddenimports、pure（模块）、datas、binaries、excludes。

为什么必须同时看 PKG 与 PYZ：PKG 里 PYZ 只是一个归档条目，PKG 校验**不能**证明
PYZ 内没有 ``ddddocr.api`` 这类未使用模块；反之源码收集模式（如 cv2 的
``module_collection_mode='py'``）的模块只以文件形式出现在 PKG。因此两者的模块名与
文件路径会合并成一个集合后再断言。

解析方式
--------
PyInstaller 的 ``*.toc`` 是 Python 字面量（tuple/list/dict）。本脚本使用
``ast.literal_eval`` 解析，**不使用** ``eval`` / ``exec``，也不执行清单引用的任何代码。
结构不符合预期时按「输入错误」失败（退出码 2），不做「尽力而为」的部分解析。

退出码
------
- 0：全部断言通过。
- 1：断言未通过（必需项缺失 / 禁止项命中）。
- 2：输入缺失、损坏或结构未知（含 PYZ 缺失导致模块级检查无法执行）。

不保证
------
清单校验只证明「收集内容」符合规则，**不能**证明 exe 可运行、OCR 可用或识别结果一致；
这些必须另行做动态验证。

用法
----
    python scripts/check_bundle.py --target full  --toc-dir <work>/GUIT-net-login-full
    python scripts/check_bundle.py --target lite  --toc-dir <work>/GUIT-net-login-lite
    python scripts/check_bundle.py --target full  --toc-dir <备份目录>/manifests/full
    python scripts/check_bundle.py --selftest --selftest-out <目录>
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import sys
import tempfile
from pathlib import Path

EXIT_PASS = 0
EXIT_ASSERT_FAILED = 1
EXIT_INPUT_ERROR = 2

PKG_NAME = "PKG-00.toc"
PYZ_NAME = "PYZ-00.toc"
ANALYSIS_NAME = "Analysis-00.toc"


class InputError(Exception):
    """输入缺失、损坏或结构未知。"""


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------
def _load_literal(path: Path):
    if not path.exists():
        raise InputError(f"清单文件不存在：{path}")
    if path.stat().st_size == 0:
        raise InputError(f"清单文件为空：{path}")
    text = path.read_text(encoding="utf-8", errors="strict")
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        raise InputError(f"清单不是可解析的 Python 字面量：{path}（{type(exc).__name__}: {exc}）") from exc


def _as_entry_list(value, where: str):
    if not isinstance(value, (list, tuple)):
        raise InputError(f"{where} 期望条目列表，实际为 {type(value).__name__}")
    out = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            raise InputError(f"{where} 存在结构未知的条目：{item!r:.120}")
        name, source, typecode = item[0], item[1], item[2]
        if not isinstance(name, str) or not isinstance(typecode, str):
            raise InputError(f"{where} 条目字段类型未知：{item!r:.120}")
        out.append((name, source if isinstance(source, str) else "", typecode.upper()))
    return out


def read_pkg(path: Path):
    obj = _load_literal(path)
    if not isinstance(obj, tuple) or len(obj) < 3:
        raise InputError(f"{path.name} 顶层结构未知（期望 tuple，长度 >= 3，实际 {type(obj).__name__}）")
    typecodes, entries = obj[1], obj[2]
    if not isinstance(typecodes, dict):
        raise InputError(f"{path.name} 的类型字典结构未知：{type(typecodes).__name__}")
    return _as_entry_list(entries, path.name)


def read_pyz(path: Path):
    obj = _load_literal(path)
    if not isinstance(obj, tuple) or len(obj) != 2 or not isinstance(obj[0], str):
        raise InputError(f"{path.name} 顶层结构未知（期望 (path, [条目])）")
    return _as_entry_list(obj[1], path.name)


def read_analysis(path: Path):
    obj = _load_literal(path)
    if not isinstance(obj, tuple) or len(obj) < 20:
        raise InputError(f"{path.name} 顶层结构未知（期望长度 >= 20 的 tuple，实际 {len(obj) if isinstance(obj, tuple) else type(obj).__name__}）")
    hiddenimports = obj[2]
    if not isinstance(hiddenimports, (list, tuple)) or not all(isinstance(x, str) for x in hiddenimports):
        raise InputError(f"{path.name} 的 hiddenimports 结构未知")
    result = {
        "hiddenimports": list(hiddenimports),
        "excludes": [x for x in obj[5] if isinstance(x, str)] if isinstance(obj[5], (list, tuple)) else [],
        "python_version": obj[12] if isinstance(obj[12], str) else "",
        "binaries": _as_entry_list(obj[15], f"{path.name}[15]"),
        "datas": _as_entry_list(obj[18], f"{path.name}[18]"),
        "pure": _as_entry_list(obj[19], f"{path.name}[19]"),
    }
    return result


# --------------------------------------------------------------------------
# 归一化
# --------------------------------------------------------------------------
def norm_path(value: str) -> str:
    return value.replace("\\", "/")


def basename_of(value: str) -> str:
    return norm_path(value).rsplit("/", 1)[-1]


def module_from_path(name: str) -> str:
    """把包内 .py 路径映射为点分模块名；非 .py 返回空串。"""
    p = norm_path(name)
    if not p.endswith(".py"):
        return ""
    p = p[:-3]
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class Manifest:
    """合并三层清单后的可断言视图。"""

    def __init__(self, target: str, toc_dir: Path):
        self.target = target
        self.toc_dir = toc_dir
        self.resources = []      # [(name, source, typecode)]
        self.modules = set()     # 点分模块名
        self.analysis = None
        self.notes = []

        pkg_path = toc_dir / PKG_NAME
        pyz_path = toc_dir / PYZ_NAME
        analysis_path = toc_dir / ANALYSIS_NAME

        self.pkg_entries = read_pkg(pkg_path)
        self.resources.extend(self.pkg_entries)
        self._seen = {(norm_path(n).lower(), t) for n, _s, t in self.pkg_entries}
        for name, _src, _tk in self.pkg_entries:
            mod = module_from_path(name)
            if mod:
                self.modules.add(mod)

        self.pyz_entries = read_pyz(pyz_path)
        for name, _src, _tk in self.pyz_entries:
            self.modules.add(name)

        if analysis_path.exists():
            self.analysis = read_analysis(analysis_path)
            # PKG 与 Analysis 的 datas/binaries 大量重叠；按 (目标名, 类型) 去重，
            # 否则体积小结与违规命中数会被双计。
            for entry in self.analysis["datas"] + self.analysis["binaries"]:
                key = (norm_path(entry[0]).lower(), entry[2])
                if key in self._seen:
                    continue
                self._seen.add(key)
                self.resources.append(entry)
            for name, _src, _tk in self.analysis["pure"]:
                self.modules.add(name)
            for name, _src, _tk in self.analysis["datas"] + self.analysis["binaries"]:
                mod = module_from_path(name)
                if mod:
                    self.modules.add(mod)
            self.modules.update(self.analysis["hiddenimports"])
        else:
            self.notes.append(f"未找到 {ANALYSIS_NAME}，本次未检查 hiddenimports / pure 模块列表")

    # -- 匹配原语（全部大小写不敏感） --
    def find_resources_exact(self, pattern: str):
        low = pattern.lower()
        return [r for r in self.resources if norm_path(r[0]).lower() == low]

    def find_resources_glob(self, pattern: str):
        pat = pattern.lower()
        return [r for r in self.resources if fnmatch.fnmatch(norm_path(r[0]).lower(), pat)]

    def find_resources_prefix(self, prefix: str):
        pre = prefix.lower()
        return [r for r in self.resources if norm_path(r[0]).lower().startswith(pre)]

    def find_resources_basename_glob(self, pattern: str):
        pat = pattern.lower()
        hits = []
        for r in self.resources:
            if fnmatch.fnmatch(basename_of(r[0]).lower(), pat):
                hits.append(r)
            elif fnmatch.fnmatch(basename_of(r[1]).lower(), pat):
                hits.append(r)
        return hits

    def find_modules_exact(self, name: str):
        low = name.lower()
        return sorted(m for m in self.modules if m.lower() == low)

    def find_modules_prefix(self, prefix: str):
        pre = prefix.lower()
        return sorted(m for m in self.modules if m.lower().startswith(pre))


# --------------------------------------------------------------------------
# 断言规则
# --------------------------------------------------------------------------
# 每条规则：(级别, 匹配方式, 模式, 说明)。级别取 "required" / "forbidden" / "notice"。
FULL_RULES = [
    # 必需：默认 OCR 模型、cv2 扩展与其实际加载配置、必要的 ONNX Runtime 库、界面资源
    ("required", "res-exact", "ddddocr/common_old.onnx", "默认 OCR 模型（old=False,beta=False 时使用）"),
    ("required", "res-exact", "cv2/cv2.pyd", "cv2 扩展模块"),
    ("required", "res-exact", "cv2/config.py", "cv2 加载配置"),
    ("required", "res-glob", "cv2/config-3*.py", "cv2 版本化加载配置"),
    ("required", "res-exact", "onnxruntime/capi/onnxruntime.dll", "ONNX Runtime 核心库"),
    ("required", "res-exact", "onnxruntime/capi/onnxruntime_pybind11_state.pyd", "ONNX Runtime Python 绑定"),
    ("required", "res-exact", "assets/app.ico", "应用图标资源"),
    # 必需：识别链路模块
    ("required", "mod", "ddddocr", "ddddocr 包"),
    ("required", "mod", "ddddocr.compat.v1", "兼容层主类"),
    ("required", "mod", "ddddocr.core.ocr_engine", "OCR 推理引擎"),
    ("required", "mod", "ddddocr.models.model_loader", "模型加载器（决定模型路径）"),
    ("required", "mod", "ddddocr.models.charset_manager", "字符集（内联在代码中）"),
    ("required", "mod", "ddddocr.preprocessing.image_processor", "预处理"),
    ("required", "mod", "ddddocr.utils.exceptions", "含 safe_import_opencv"),
    ("required", "mod", "numpy", "ddddocr 运行时依赖"),
    ("required", "mod", "cv2", "OpenCV"),
    ("required", "mod", "onnxruntime", "ONNX Runtime"),
    # 必需：界面与托盘（full 同样需要）
    ("required", "mod", "PIL.ImageTk", "验证码图片显示"),
    ("required", "mod", "pystray._win32", "托盘后端"),
    # 禁止：闲置模型与任意目录下的 FFmpeg 视频组件
    ("forbidden", "res-exact", "ddddocr/common.onnx", "闲置 beta 模型（仅 beta=True 时使用）"),
    ("forbidden", "res-exact", "ddddocr/common_det.onnx", "闲置目标检测模型（仅 det=True 时使用）"),
    ("forbidden", "res-basename", "opencv_videoio_ffmpeg*.dll", "闲置 FFmpeg 视频组件（任意目录）"),
    # 禁止：未使用的 HTTP 服务子包（资源与 PYZ 模块两个来源都查）
    ("forbidden", "res-prefix", "ddddocr/api/", "未使用的 HTTP 服务子包"),
    ("forbidden", "mod", "ddddocr.api", "未使用的 HTTP 服务子包"),
    ("forbidden", "mod-prefix", "ddddocr.api.", "未使用的 HTTP 服务子包"),
    # 提示：不影响判定，仅报告
    ("notice", "res-exact", "ddddocr/charsets.py", "死代码（无模块引用；字符集内联在 charset_manager）"),
    ("notice", "res-exact", "ddddocr/logo.png", "闲置图片"),
    ("notice", "res-exact", "ddddocr/README.md", "上游说明文件"),
    ("notice", "mod", "ddddocr.__main__", "CLI 入口，GUI 不使用"),
    ("notice", "mod", "ddddocr.charsets", "死代码模块"),
]

_LITE_OCR_PACKAGES = ["ddddocr", "cv2", "onnxruntime", "numpy", "sympy", "matplotlib"]

LITE_RULES = [
    # 必需：界面基础能力（Pillow 图片解码、pystray 托盘、Tk/Tcl、应用图标）
    ("required", "mod", "PIL.ImageTk", "验证码图片显示"),
    ("required", "mod", "pystray._win32", "托盘后端"),
    ("required", "mod", "tkinter", "GUI 主体"),
    ("required", "res-exact", "assets/app.ico", "应用图标资源"),
    ("required", "res-basename", "tk86t.dll", "Tk 运行库"),
    ("required", "res-basename", "tcl86t.dll", "Tcl 运行库"),
    ("required", "res-prefix", "_tk_data/", "Tk 数据文件"),
    ("required", "res-prefix", "_tcl_data/", "Tcl 数据文件"),
    # 禁止：lit 不含任何 OCR 相关资源或模块
    ("forbidden", "res-prefix", "ddddocr/", "lite 不含 OCR"),
    ("forbidden", "res-prefix", "cv2/", "lite 不含 OCR"),
    ("forbidden", "res-prefix", "onnxruntime/", "lite 不含 OCR"),
    ("forbidden", "res-prefix", "numpy/", "lite 不含 numpy"),
    ("forbidden", "res-prefix", "numpy.libs/", "lite 不含 numpy"),
    ("forbidden", "res-basename", "opencv_videoio_ffmpeg*.dll", "lite 不应出现 FFmpeg 组件"),
]

for _pkg in _LITE_OCR_PACKAGES:
    LITE_RULES.append(("forbidden", "mod", _pkg, f"lite 不含 {_pkg}"))
    LITE_RULES.append(("forbidden", "mod-prefix", f"{_pkg}.", f"lite 不含 {_pkg} 子模块"))


def rule_hits(manifest: Manifest, kind: str, pattern: str):
    if kind == "res-exact":
        return [(r[0], r[2]) for r in manifest.find_resources_exact(pattern)]
    if kind == "res-glob":
        return [(r[0], r[2]) for r in manifest.find_resources_glob(pattern)]
    if kind == "res-prefix":
        return [(r[0], r[2]) for r in manifest.find_resources_prefix(pattern)]
    if kind == "res-basename":
        return [(r[0], r[2]) for r in manifest.find_resources_basename_glob(pattern)]
    if kind == "mod":
        return [(m, "PYMODULE") for m in manifest.find_modules_exact(pattern)]
    if kind == "mod-prefix":
        return [(m, "PYMODULE") for m in manifest.find_modules_prefix(pattern)]
    raise InputError(f"未知的匹配方式：{kind}")


def run_checks(manifest: Manifest, rules):
    """返回 (failures, notices, lines)。"""
    failures = []
    notices = []
    lines = []
    grouped = {}
    for level, kind, pattern, why in rules:
        hits = rule_hits(manifest, kind, pattern)
        grouped.setdefault(level, []).append((pattern, why, hits))
        if level == "required" and not hits:
            failures.append(f"缺必需项：{pattern}（{why}）")
            lines.append(("失败", f"必须存在但缺失：{pattern}　<{why}>"))
        elif level == "required":
            lines.append(("通过", f"必须存在：{pattern}"))
        elif level == "forbidden" and hits:
            failures.append(f"出现禁止项：{pattern}（{why}，命中 {len(hits)} 项）")
            lines.append(("失败", f"不应收集却出现：{pattern}　<{why}>　命中 {len(hits)} 项"))
            for name, tk in hits[:12]:
                lines.append(("明细", f"{name}  [{tk}]"))
            if len(hits) > 12:
                lines.append(("明细", f"...另有 {len(hits) - 12} 项"))
        elif level == "forbidden":
            lines.append(("通过", f"必须不存在：{pattern}"))
        else:
            if hits:
                notices.append(f"{pattern}（{why}）命中 {len(hits)} 项")
                lines.append(("提示", f"可进一步精简（不影响判定）：{pattern}　<{why}>　命中 {len(hits)} 项"))
    return failures, notices, lines


# --------------------------------------------------------------------------
# 体积小结
# --------------------------------------------------------------------------
def size_summary(manifest: Manifest):
    groups = {}
    for name, source, _tk in manifest.resources:
        top = norm_path(name).split("/", 1)[0]
        bucket = groups.setdefault(top, {"count": 0, "bytes": 0, "missing": 0})
        bucket["count"] += 1
        if source and Path(source).exists():
            try:
                bucket["bytes"] += Path(source).stat().st_size
            except OSError:
                bucket["missing"] += 1
        else:
            bucket["missing"] += 1
    return groups


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def check_target(target: str, toc_dir: Path, as_json: Path | None, out=print) -> int:
    out(f"==== 校验 PyInstaller 清单（{target}） ====")
    out(f"清单目录：{toc_dir}")
    try:
        manifest = Manifest(target, toc_dir)
    except InputError as exc:
        out(f"[输入错误] {exc}")
        out("[结果] 无法完成校验；退出码 2。")
        return EXIT_INPUT_ERROR

    out(f"  PKG-00.toc      条目 {len(manifest.pkg_entries)}")
    out(f"  PYZ-00.toc      模块 {len(manifest.pyz_entries)}")
    if manifest.analysis:
        a = manifest.analysis
        out(f"  Analysis-00.toc hiddenimports {len(a['hiddenimports'])} / pure {len(a['pure'])}"
            f" / datas {len(a['datas'])} / binaries {len(a['binaries'])} / excludes {len(a['excludes'])}")
        out(f"                  构建解释器 {a['python_version'][:60]}")
    out(f"  合并后：资源 {len(manifest.resources)} 条、模块 {len(manifest.modules)} 个")
    for note in manifest.notes:
        out(f"  [注意] {note}")

    rules = FULL_RULES if target == "full" else LITE_RULES
    failures, notices, lines = run_checks(manifest, rules)
    for tag, text in lines:
        prefix = {"通过": "[通过]", "失败": "[失败]", "提示": "[提示]"}.get(tag, "        ")
        out(f"{prefix} {text}" if tag != "明细" else f"        {text}")

    out("---- 已收集资源分组（源文件原始字节，非 exe 缩减量） ----")
    summary = size_summary(manifest)
    for top in sorted(summary):
        info = summary[top]
        mb = info["bytes"] / 1048576
        out(f"  {top:<26} {info['count']:>5} 项 {info['bytes']:>12} 字节 {mb:>8.2f} MiB"
            + (f"（{info['missing']} 项源文件不在本机）" if info["missing"] else ""))

    if as_json is not None:
        payload = {
            "target": target,
            "toc_dir": str(toc_dir),
            "counts": {
                "pkg_entries": len(manifest.pkg_entries),
                "pyz_modules": len(manifest.pyz_entries),
                "resources": len(manifest.resources),
                "modules": len(manifest.modules),
            },
            "failures": failures,
            "notices": notices,
            "size_groups": summary,
        }
        as_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        out(f"已写出 JSON 报告：{as_json}")

    out("")
    if not failures:
        out(f"[结果] 通过。收集内容符合阶段 A 规则（{target}）；退出码 0。")
        out("提示：清单校验不能证明运行成功，仍需在无 Python 环境实测 exe 的 OCR 与界面功能。")
        return EXIT_PASS
    out(f"[结果] 不通过，共 {len(failures)} 项问题：")
    for f in failures:
        out(f"  - {f}")
    out("产物不可发布；请检查 scripts/build.ps1 与 scripts/hooks/ 下的收集规则。退出码 1。")
    return EXIT_ASSERT_FAILED


# --------------------------------------------------------------------------
# 自检样例
# --------------------------------------------------------------------------
def _entry(name, source="", typecode="DATA"):
    return (name, source, typecode)


def write_fixture(root: Path, case: str):
    """写出一个合成清单样例目录，返回 (目录, 期望退出码)。"""
    d = root / case
    d.mkdir(parents=True, exist_ok=True)

    def pkg(entries):
        body = ",\n ".join(repr(e) for e in entries)
        (d / PKG_NAME).write_text(
            "('X:/fake/pkg.pkg',\n {'DATA': True},\n [" + body + "],\n 'python313.dll',\n False,\n False,\n False,\n [],\n None,\n None,\n None)\n",
            encoding="utf-8",
        )

    def pyz(modules):
        body = ",\n ".join(repr((m, "C:/fake/" + m.replace(".", "/") + ".py", "PYMODULE")) for m in modules)
        (d / PYZ_NAME).write_text("('X:/fake/PYZ-00.pyz',\n [" + body + "])\n", encoding="utf-8")

    def analysis(hidden, pure, datas, binaries, excludes):
        def toc(items):
            return "[" + ",\n ".join(repr(i) for i in items) + "]"
        (d / ANALYSIS_NAME).write_text(
            "([],[],"
            + repr(list(hidden)) + ",[],{},"
            + repr(list(excludes)) + ",[],False,{},0,[],"
            + toc(datas) + ","
            + repr("3.13.16 (fake)") + ",[],"
            + toc(pure) + ","
            + toc(binaries) + ",[],[],"
            + toc(datas) + ","
            + toc(pure) + ")\n",
            encoding="utf-8",
        )

    if case == "full_ok":
        # 覆盖：转义路径、含空格与中文的源目录、双反斜杠写法、非 ASCII 文件名
        pkg([
            _entry(r"ddddocr\common_old.onnx", r"D:\Dev\.venv\Lib\site-packages\ddddocr\common_old.onnx"),
            _entry(r"cv2\cv2.pyd", r"D:\Dev\.venv\Lib\site-packages\cv2\cv2.pyd", "EXTENSION"),
            _entry(r"cv2\config.py", r"D:\Dev\.venv\Lib\site-packages\cv2\config.py"),
            _entry(r"cv2\config-3.py", r"D:\Dev\.venv\Lib\site-packages\cv2\config-3.py"),
            _entry(r"onnxruntime\capi\onnxruntime.dll", r"D:\Dev\.venv\Lib\site-packages\onnxruntime\capi\onnxruntime.dll", "BINARY"),
            _entry(r"onnxruntime\capi\onnxruntime_pybind11_state.pyd", r"D:\Dev\.venv\Lib\site-packages\onnxruntime\capi\onnxruntime_pybind11_state.pyd", "EXTENSION"),
            _entry(r"assets\app.ico", r"D:\Dev 项目\GUIT-net-login\assets\app.ico"),
            _entry(r"gui\_tk_data\中文 图片.gif", r"D:\Dev 项目\assets\中文 图片.gif"),
        ])
        pyz(["ddddocr", "ddddocr.compat.v1", "ddddocr.core.ocr_engine", "ddddocr.models.model_loader",
             "ddddocr.models.charset_manager", "ddddocr.preprocessing.image_processor",
             "ddddocr.utils.exceptions", "numpy", "cv2", "onnxruntime", "PIL.ImageTk", "pystray._win32"])
        analysis(["ddddocr", "pystray._win32", "PIL.ImageTk"], [], [], [], [])
        return d, EXIT_PASS

    if case == "full_violations":
        pkg([
            _entry(r"ddddocr\common_old.onnx"),
            _entry(r"ddddocr\common.onnx"),
            _entry(r"ddddocr\common_det.onnx"),
            _entry(r"ddddocr\api\app.py"),
            _entry(r"ddddocr\api\routes.py"),
            _entry("opencv_videoio_ffmpeg500_64.dll"),                    # 根目录，用于验证不只看 cv2/ 前缀
            _entry("some-dir\\opencv_videoio_ffmpeg500_64.dll"),          # 其他目录，源路径匹配
            _entry(r"cv2\cv2.pyd", "", "EXTENSION"),
            _entry(r"cv2\config.py"),
            _entry(r"cv2\config-3.py"),
            _entry(r"onnxruntime\capi\onnxruntime.dll", "", "BINARY"),
            _entry(r"onnxruntime\capi\onnxruntime_pybind11_state.pyd", "", "EXTENSION"),
            _entry(r"assets\app.ico"),
        ])
        pyz(["ddddocr", "ddddocr.compat.v1", "ddddocr.core.ocr_engine", "ddddocr.models.model_loader",
             "ddddocr.models.charset_manager", "ddddocr.preprocessing.image_processor",
             "ddddocr.utils.exceptions", "numpy", "cv2", "onnxruntime", "PIL.ImageTk", "pystray._win32",
             "ddddocr.api", "ddddocr.api.routes"])
        analysis([], [], [], [], [])
        return d, EXIT_ASSERT_FAILED

    if case == "full_missing_model":
        pkg([
            _entry(r"cv2\cv2.pyd", "", "EXTENSION"), _entry(r"cv2\config.py"),
            _entry(r"cv2\config-3.py"),
            _entry(r"onnxruntime\capi\onnxruntime.dll", "", "BINARY"),
            _entry(r"onnxruntime\capi\onnxruntime_pybind11_state.pyd", "", "EXTENSION"),
            _entry(r"assets\app.ico"),
        ])
        pyz(["ddddocr", "ddddocr.compat.v1", "ddddocr.core.ocr_engine", "ddddocr.models.model_loader",
             "ddddocr.models.charset_manager", "ddddocr.preprocessing.image_processor",
             "ddddocr.utils.exceptions", "numpy", "cv2", "onnxruntime", "PIL.ImageTk", "pystray._win32"])
        analysis([], [], [], [], [])
        return d, EXIT_ASSERT_FAILED

    if case == "lite_ok":
        pkg([
            _entry(r"assets\app.ico"),
            _entry("tk86t.dll", "", "BINARY"), _entry("tcl86t.dll", "", "BINARY"),
            _entry(r"_tk_data\images\logo.gif"), _entry(r"_tcl_data\encoding\ascii.enc"),
        ])
        pyz(["PIL.ImageTk", "pystray._win32", "tkinter", "tkinter.filedialog"])
        analysis(["pystray._win32", "PIL.ImageTk"], [], [], [], ["ddddocr", "cv2", "numpy"])
        return d, EXIT_PASS

    if case == "lite_wrong_ocr":
        pkg([
            _entry(r"assets\app.ico"), _entry("tk86t.dll", "", "BINARY"), _entry("tcl86t.dll", "", "BINARY"),
            _entry(r"_tk_data\images\logo.gif"), _entry(r"_tcl_data\encoding\ascii.enc"),
            _entry(r"ddddocr\common_old.onnx"), _entry(r"cv2\cv2.pyd", "", "EXTENSION"),
        ])
        pyz(["PIL.ImageTk", "pystray._win32", "tkinter", "ddddocr", "cv2", "numpy"])
        analysis([], [], [], [], [])
        return d, EXIT_ASSERT_FAILED

    if case == "unknown_structure":
        (d / PKG_NAME).write_text("{'not': 'a toc'}\n", encoding="utf-8")
        pyz(["x"])
        return d, EXIT_INPUT_ERROR

    if case == "broken_literal":
        (d / PKG_NAME).write_text("('unterminated\n", encoding="utf-8")
        return d, EXIT_INPUT_ERROR

    if case == "missing_pyz":
        pkg([_entry(r"assets\\app.ico")])
        return d, EXIT_INPUT_ERROR

    raise ValueError(f"未知样例：{case}")


SELFTEST_CASES = [
    "full_ok", "full_violations", "full_missing_model",
    "lite_ok", "lite_wrong_ocr",
    "unknown_structure", "broken_literal", "missing_pyz",
]
SELFTEST_TARGET = {
    "full_ok": "full", "full_violations": "full", "full_missing_model": "full",
    "lite_ok": "lite", "lite_wrong_ocr": "lite",
    "unknown_structure": "full", "broken_literal": "full", "missing_pyz": "full",
}


def selftest(keep_dir: Path | None) -> int:
    root = keep_dir or Path(tempfile.mkdtemp(prefix="check-bundle-selftest-"))
    root.mkdir(parents=True, exist_ok=True)
    ok = True
    print(f"==== 检查器自检（合成清单样例） ====")
    print(f"样例目录：{root}")
    for case in SELFTEST_CASES:
        d, expected = write_fixture(root, case)
        target = SELFTEST_TARGET[case]
        print(f"---- 样例 {case}（target={target}，期望退出码 {expected}） ----")
        got = check_target(target, d, None, out=print)
        verdict = "符合预期" if got == expected else "与预期不符"
        if got != expected:
            ok = False
        print(f"[样例结论] {case}：退出码 {got}，{verdict}")
        print("")
    print(f"[自检总结果] {'全部样例符合预期' if ok else '存在与预期不符的样例'}")
    return EXIT_PASS if ok else EXIT_ASSERT_FAILED


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PyInstaller 打包清单检查器（只读，标准库）")
    parser.add_argument("--target", choices=["full", "lite"], help="构建目标")
    parser.add_argument("--toc-dir", type=Path, help="包含 PKG-00.toc / PYZ-00.toc 的目录")
    parser.add_argument("--json", type=Path, default=None, help="可选：写出 JSON 报告")
    parser.add_argument("--selftest", action="store_true", help="运行内置合成样例自检")
    parser.add_argument("--selftest-out", type=Path, default=None, help="自检样例输出目录（默认临时目录）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest(args.selftest_out)

    if not args.target or not args.toc_dir:
        parser.error("需要同时提供 --target 与 --toc-dir（或使用 --selftest）")
    return check_target(args.target, args.toc_dir, args.json)


if __name__ == "__main__":
    sys.exit(main())
