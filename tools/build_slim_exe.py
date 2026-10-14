"""Build a slim onefile exe by reusing the original PyInstaller bootloader and rebuilding the PKG.

Approach: the original exe is [bootloader PE][CArchive PKG]. We keep the bootloader bytes verbatim and
write a new PKG (same CArchive format) that
  * replaces the first-party modules with our (fixed) compiled sources,
  * drops provably unused payload (OpenCV、未用 PIL 扩展、死标准库等，见下方排除表),
  * rebuilds the PYZ without the dropped modules,
  * recompresses everything at zlib level 9.

实测（2026-10-14，基底为 v1.0.14 的 full exe 85,643,184 字节）：
  用户已有精简版（只去 cv2 + 2 个 PIL 扩展）          47.71 MiB
  本工具默认配方（再裁 PKG/PYZ 死重量，OCR 行为不变）   45.29 MiB
  验证：包内 OcrEngine.available() 为 True；对 120 张固定样本的包装输出与
        full 版逐张一致（差异 0）；GUI 冒烟通过（窗口/单实例端口/正常退出）。

**不可删除的实测教训**（改排除表前请先读）：
  * `numpy.libs\\*`（openblas）删掉后 numpy 直接导入失败——`_multiarray_umath.pyd`
    对 openblas 是**加载期**依赖，不是懒加载；
  * `numpy._core._add_newdocs` 被 `numpy._core/__init__` 导入期引用；
  * `numpy.ma` 被 `numpy.matrixlib` 链式引用。
    结论：numpy 的任何子模块都不要放进 PYZ 排除表。

用法：
  python tools/build_slim_exe.py --exe build/GUIT-net-login-full.exe --proj . --src src --out build/GUIT-net-login-slim.exe
  python tools/build_slim_exe.py --dry                       # 只估算，不写文件
  python tools/build_slim_exe.py --keep-all   --out <p.exe>  # 二分：保留全部 PKG 条目
  python tools/build_slim_exe.py --no-pyz-trim --out <p.exe> # 二分：PYZ 不做裁剪
  python tools/build_slim_exe.py --no-replace --out <p.exe>  # 二分：不替换第一方模块
  python tools/build_slim_exe.py --control    --out <p.exe>  # 二分：只重打包不改内容
  python tools/build_slim_exe.py --probe <entry.py> --out <p.exe>   # 诊断入口
"""
import argparse
import marshal
import os
import re
import struct
import sys
import zlib

# 重打包基底（full 版 exe）与项目目录均可通过 CLI 参数或环境变量指定，不硬编码本机路径：
#   GUIT_FULL_EXE / GUIT_PROJ 环境变量，或 --exe / --proj / --src 参数
EXE = os.environ.get('GUIT_FULL_EXE', '')
PROJ = os.environ.get('GUIT_PROJ', '')
MAGIC = b'MEI\014\013\012\013\016'
COOKIE = '!8sIIII64s'
COOKIE_LEN = struct.calcsize(COOKIE)
TOC_FMT = '!IIIIBc'
TOC_LEN = struct.calcsize(TOC_FMT)

ENTRY = 'app'                                                  # PKG entry script (name must stay)
PYZ_MODULES = ('portal_client', 'config_store', 'ocr_helper', 'app_logger', 'autostart')

# ---- PKG 层排除 ----
# 前缀排除：整个 OpenCV（OCR 路径不访问 cv2 属性，由 src/ocr_helper.py 的 cv2 桩兜底）
PKG_EXCLUDE_PREFIX = (
    'cv2\\',
)
# 精确排除：未用到的 PIL C 扩展 + ONNX Runtime 的共享 provider DLL（CPU EP 不需要）
PKG_EXCLUDE_EXACT = (
    'PIL\\_avif.cp313-win_amd64.pyd',          # AVIF 解码（4.1 MiB）
    'PIL\\_imagingft.cp313-win_amd64.pyd',     # FreeType 字体（界面不用 PIL 画字）
    'PIL\\_webp.cp313-win_amd64.pyd',          # WebP 解码
    'PIL\\_imagingcms.cp313-win_amd64.pyd',    # 色彩管理
    'PIL\\_imagingmath.cp313-win_amd64.pyd',   # 图像数学运算
    'onnxruntime\\capi\\onnxruntime_providers_shared.dll',
)

# ---- PYZ 层排除（模块名前缀）----
# onnxruntime 只留运行路径（__init__/capi），量化/工具/transformers 是纯 Python 死重量；
# pydoc/unittest/xml/_pydecimal/asyncio 在 GUI 程序中均无引用。
# 注意：numpy.* 一律不许进入本表（见文件头「不可删除的实测教训」）。
PYZ_DROP_PREFIXES = (
    'onnxruntime.quantization',
    'onnxruntime.tools',
    'onnxruntime.transformers',
    'onnxruntime.datasets',
    'pydoc',
    'unittest',
    'xml',
    '_pydecimal',
    'asyncio',
)
# PIL 只保留 PNG 解码（验证码是 PNG）；其余 *ImagePlugin / *ImageFile 依赖 Image.init()
# 的容错加载（Pillow 对缺失插件会跳过，不抛错）。
_PIL_PLUGIN_RE = re.compile(r'^PIL\.[A-Za-z0-9_]+ImagePlugin$')
_PIL_FILE_RE = re.compile(r'^PIL\.[A-Za-z0-9_]+ImageFile$')
PIL_KEEP_PLUGIN = 'PIL.PngImagePlugin'

KEEP_ALL = False
NO_REPLACE = False
NO_PYZ_TRIM = False


def norm(name):
    return name.replace('/', '\\')


def excluded(name):
    if KEEP_ALL:
        return False
    n = norm(name)
    return n.startswith(PKG_EXCLUDE_PREFIX) or n in PKG_EXCLUDE_EXACT


def pyz_excluded(name):
    if NO_PYZ_TRIM:
        return False
    if name.startswith(PYZ_DROP_PREFIXES):
        return True
    if _PIL_PLUGIN_RE.match(name) and name != PIL_KEEP_PLUGIN:
        return True
    if _PIL_FILE_RE.match(name):
        return True
    return False


def read_archive(path):
    raw = open(path, 'rb').read()
    off = raw.rfind(MAGIC)
    if off < 0:
        raise SystemExit('!! 未在 %s 中找到 PyInstaller cookie（不是 onefile 产物？）' % path)
    _m, alen, tocoff, toclen, pyvers, pylib = struct.unpack(COOKIE, raw[off:off + COOKIE_LEN])
    start = off + COOKIE_LEN - alen
    data = raw[start + tocoff: start + tocoff + toclen]
    ordered, p = [], 0
    while p < len(data):
        elen, eoff, dlen, ulen, cflag, tc = struct.unpack(TOC_FMT, data[p:p + TOC_LEN])
        name = data[p + TOC_LEN:p + elen].rstrip(b'\0').decode('utf-8')
        ordered.append((name, (eoff, dlen, ulen, cflag, tc.decode())))
        p += elen
    return raw, start, ordered, pyvers, pylib


def entry_raw(raw, start, e):
    """Stored bytes of an entry (still compressed if it was stored compressed)."""
    eoff, dlen, _ulen, _cflag, _tc = e
    return raw[start + eoff: start + eoff + dlen]


def entry_data(raw, start, e):
    """Decompressed payload of an entry."""
    eoff, dlen, _ulen, cflag, _tc = e
    blob = raw[start + eoff: start + eoff + dlen]
    return zlib.decompress(blob) if cflag else blob


def compile_module(path, filename):
    return marshal.dumps(compile(open(path, encoding='utf-8').read(), filename, 'exec'))


def build_pyz(orig, replacements):
    """Rebuild the PYZ (ZlibArchive) with our modules swapped in; other entries copied verbatim."""
    assert orig[:4] == b'PYZ\0'
    pyc_magic = orig[4:8]
    toc_off = struct.unpack('!i', orig[8:12])[0]
    entries = marshal.loads(orig[toc_off:])
    out = bytearray(b'PYZ\0' + pyc_magic + b'\x00\x00\x00\x00')
    new_toc, replaced = [], set()
    dropped = saved = 0
    for name, (typ, off, length) in entries:
        if pyz_excluded(name):
            dropped += 1
            saved += length
            continue
        if name in replacements:
            blob = zlib.compress(replacements[name], 9)
            typ = 0                                   # PYZ_ITEM_MODULE
            replaced.add(name)
        else:
            blob = orig[off:off + length]
        at = len(out)
        out += blob
        new_toc.append((name, (typ, at, len(blob))))
    for name in sorted(set(replacements) - replaced):
        blob = zlib.compress(replacements[name], 9)
        at = len(out)
        out += blob
        new_toc.append((name, (0, at, len(blob))))
    toc_at = len(out)
    out += marshal.dumps(new_toc)
    struct.pack_into('!i', out, 8, toc_at)
    return bytes(out), len(entries), len(new_toc), dropped, saved


def build_pkg(ordered, raw, start, replacements, level=9, control=False):
    blobs, toc_items, cursor, stored = [], [], 0, 0
    dropped = saved = 0
    for name, e in ordered:
        if not control and excluded(name):
            dropped += 1
            saved += e[1]
            continue
        if control:
            blob, cflag, raw_len = entry_raw(raw, start, e), e[3], e[2]
        else:
            payload = replacements.get(name)
            if payload is None:
                payload = entry_data(raw, start, e)
            # Preserve the original per-entry compression convention: the bootloader extracts some
            # entries (notably the PYZ, typecode 'z') WITHOUT inflating them, so the flag must match.
            if e[3]:
                blob, cflag = zlib.compress(payload, level), 1
            else:
                blob, cflag = payload, 0
            raw_len = len(payload)
        stored += len(blob)
        name_b = name.encode('utf-8')
        # PyInstaller's writer: entry_len = 18 + len(name) + 1 (NUL terminator), then rounded up to 16.
        entry_len = TOC_LEN + len(name_b) + 1
        pad = (-entry_len) % 16
        entry_len += pad
        toc_items.append(struct.pack(TOC_FMT, entry_len, cursor, len(blob), raw_len, cflag,
                                     e[4].encode('ascii')) + name_b + b'\0' * (1 + pad))
        blobs.append(blob)
        cursor += len(blob)
    toc = b''.join(toc_items)
    pkg_len = cursor + len(toc) + COOKIE_LEN
    cookie = struct.pack(COOKIE, MAGIC, pkg_len, cursor, len(toc), 313, b'python313.dll')
    return b''.join(blobs) + toc + cookie, stored, len(toc_items), dropped, saved


def main():
    global EXE, PROJ, KEEP_ALL, NO_REPLACE, NO_PYZ_TRIM
    ap = argparse.ArgumentParser()
    ap.add_argument('--out')
    ap.add_argument('--exe', default=EXE, help='full 版 exe 路径（重打包基底；或设 GUIT_FULL_EXE）')
    ap.add_argument('--proj', default=PROJ, help='项目目录（或设 GUIT_PROJ）')
    ap.add_argument('--src', default='', help='第一方模块所在目录（repo 布局为 src；默认自动探测）')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--level', type=int, default=9)
    ap.add_argument('--probe', help='diagnostic entry script (replaces app)')
    ap.add_argument('--control', action='store_true')
    ap.add_argument('--keep-all', action='store_true')
    ap.add_argument('--no-replace', action='store_true')
    ap.add_argument('--no-pyz-trim', action='store_true')
    args = ap.parse_args()

    EXE, PROJ = args.exe, args.proj
    KEEP_ALL = args.keep_all
    NO_REPLACE = args.no_replace
    NO_PYZ_TRIM = args.no_pyz_trim
    src_dir = args.src or (os.path.join(PROJ, 'src') if os.path.isdir(os.path.join(PROJ, 'src')) else PROJ)
    if not EXE or not os.path.isfile(EXE):
        print('!! 未找到 full 版 exe：请用 --exe 或环境变量 GUIT_FULL_EXE 指定重打包基底')
        return 2
    if not args.no_replace and not os.path.isfile(os.path.join(src_dir, 'app.py')):
        print('!! 未找到 app.py：请用 --proj/--src 指定模块目录')
        return 2

    raw, start, ordered, pyvers, pylib = read_archive(EXE)
    orig_size = len(raw)
    print('original exe      : %d bytes (%.2f MiB)' % (orig_size, orig_size / 1048576))
    print('bootloader prefix : %d bytes' % start)
    print('PKG entries       : %d' % len(ordered))
    orig_stored = sum(e[1] for _n, e in ordered)
    dropped = [(n, e[1]) for n, e in ordered if excluded(n)]
    print('PKG stored total  : %.2f MiB' % (orig_stored / 1048576))
    print('dropped entries   : %d, stored %.2f MiB' % (len(dropped), sum(s for _n, s in dropped) / 1048576))
    for n, s in dropped:
        print('    - %-46s %7.2f MiB' % (n, s / 1048576))

    repl = {}
    if not args.no_replace:
        if args.probe:
            src = open(args.probe, encoding='utf-8').read()
            repl[ENTRY] = marshal.dumps(compile(src, os.path.basename(args.probe), 'exec'))
            print('entry script      : probe %s' % args.probe)
        else:
            repl[ENTRY] = compile_module(os.path.join(src_dir, 'app.py'), 'app.py')
        for m in PYZ_MODULES:
            repl[m] = compile_module(os.path.join(src_dir, m + '.py'), m + '.py')
        print('recompiled        : %s + %s' % (ENTRY, ', '.join(PYZ_MODULES)))

        pyz = entry_data(raw, start, dict(ordered)['PYZ.pyz'])
        new_pyz, n_old, n_new, pyz_drop, pyz_saved = build_pyz(pyz, {m: repl[m] for m in PYZ_MODULES})
        repl['PYZ.pyz'] = new_pyz
        print('PYZ rebuilt       : %d -> %d modules（剔除 %d，省 %.2f MiB）, %.2f MiB (was %.2f MiB)' % (
            n_old, n_new, pyz_drop, pyz_saved / 1048576, len(new_pyz) / 1048576, len(pyz) / 1048576))
    else:
        print('modules           : kept original (--no-replace)')

    pkg, stored_total, n_toc, pkg_drop, pkg_saved = build_pkg(ordered, raw, start, repl, level=args.level,
                                                              control=args.control)
    new_size = start + len(pkg)
    print('new PKG           : %d entries, stored %.2f MiB' % (n_toc, stored_total / 1048576))
    print('new exe           : %d bytes (%.2f MiB)  change %+.1f%%' % (
        new_size, new_size / 1048576, (new_size / orig_size - 1) * 100))

    if args.dry or not args.out:
        return 0
    with open(args.out, 'wb') as fp:
        fp.write(raw[:start])
        fp.write(pkg)
    real = os.path.getsize(args.out)
    print('written           : %s (%d bytes, %.2f MiB)' % (args.out, real, real / 1048576))
    if real != new_size:
        print('!! size mismatch: %d vs %d' % (real, new_size))
        return 2

    # 自校验：重新解析产物，确认仍是合法 onefile 且条目数与写出一致
    try:
        _raw2, _start2, ordered2, _pv2, _pl2 = read_archive(args.out)
        if len(ordered2) != n_toc:
            print('!! 自校验失败：回读条目数 %d != 写出 %d' % (len(ordered2), n_toc))
            return 2
        if _start2 != start:
            print('!! 自校验失败：引导器长度变化 %d != %d' % (_start2, start))
            return 2
    except Exception as exc:  # noqa: BLE001
        print('!! 自校验失败：%r' % (exc,))
        return 2
    print('self-check        : OK（回读 %d 条目，引导器 %d 字节）' % (len(ordered2), _start2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
