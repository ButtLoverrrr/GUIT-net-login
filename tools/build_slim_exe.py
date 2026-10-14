"""Build a slim onefile exe by reusing the original PyInstaller bootloader and rebuilding the PKG.

Approach: the original exe is [bootloader PE][CArchive PKG]. We keep the bootloader bytes verbatim and
write a new PKG (same CArchive format) that
  * replaces the first-party modules with our (fixed) compiled sources,
  * drops provably unused payload (OpenCV etc.),
  * recompresses everything at zlib level 9.

Usage (run with the bundled 3.13 interpreter):
  py313 build_slim_exe.py --dry
  py313 build_slim_exe.py --out <path.exe>
  py313 build_slim_exe.py --control --out <path.exe>      # bisect: repack only, no content change
  py313 build_slim_exe.py --keep-all  --out <path.exe>    # bisect: keep every entry
  py313 build_slim_exe.py --no-replace --out <path.exe>   # bisect: original modules
  py313 build_slim_exe.py --probe <entry.py> --out <path.exe>   # diagnostic entry script
"""
import argparse
import marshal
import os
import struct
import sys
import zlib

# 重打包基底（full 版 exe）与项目目录均可通过 CLI 参数或环境变量指定，不再硬编码本机路径：
#   GUIT_FULL_EXE / GUIT_PROJ 环境变量，或 --exe / --proj / --src 参数
#   （repo 布局下模块在 src/ 子目录，--src 不给时自动探测）。
EXE = os.environ.get('GUIT_FULL_EXE', '')
PROJ = os.environ.get('GUIT_PROJ', '')
MAGIC = b'MEI\014\013\012\013\016'
COOKIE = '!8sIIII64s'
COOKIE_LEN = struct.calcsize(COOKIE)
TOC_FMT = '!IIIIBc'
TOC_LEN = struct.calcsize(TOC_FMT)

ENTRY = 'app'                                                  # PKG entry script (name must stay)
PYZ_MODULES = ('portal_client', 'config_store', 'ocr_helper', 'app_logger', 'autostart')

# Payload dropped from the slim build (proven unused: see reports/PACKAGING.md)
EXCLUDE_EXACT = (
    'PIL\\_avif.cp313-win_amd64.pyd',
    'PIL\\_imagingft.cp313-win_amd64.pyd',
)

KEEP_ALL = False
NO_REPLACE = False


def norm(name):
    return name.replace('/', '\\')


def excluded(name):
    if KEEP_ALL:
        return False
    n = norm(name)
    return n.startswith('cv2\\') or n in EXCLUDE_EXACT


def read_archive(path):
    raw = open(path, 'rb').read()
    off = raw.rfind(MAGIC)
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
    for name, (typ, off, length) in entries:
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
    return bytes(out), len(entries), len(new_toc)


def build_pkg(ordered, raw, start, replacements, level=9, control=False):
    blobs, toc_items, cursor, stored = [], [], 0, 0
    for name, e in ordered:
        if not control and excluded(name):
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
    return b''.join(blobs) + toc + cookie, stored, len(toc_items)


def main():
    global EXE, PROJ
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
    args = ap.parse_args()

    EXE, PROJ = args.exe, args.proj
    src_dir = args.src or (os.path.join(PROJ, 'src') if os.path.isdir(os.path.join(PROJ, 'src')) else PROJ)
    if not EXE or not os.path.isfile(EXE):
        print('!! 未找到 full 版 exe：请用 --exe 或环境变量 GUIT_FULL_EXE 指定重打包基底')
        return 2
    if not args.no_replace and not os.path.isfile(os.path.join(src_dir, 'app.py')):
        print('!! 未找到 app.py：请用 --proj/--src 指定模块目录')
        return 2

    global KEEP_ALL, NO_REPLACE
    KEEP_ALL = args.keep_all
    NO_REPLACE = args.no_replace

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
        new_pyz, n_old, n_new = build_pyz(pyz, {m: repl[m] for m in PYZ_MODULES})
        repl['PYZ.pyz'] = new_pyz
        print('PYZ rebuilt       : %d -> %d modules, %.2f MiB (was %.2f MiB)' % (
            n_old, n_new, len(new_pyz) / 1048576, len(pyz) / 1048576))
    else:
        print('modules           : kept original (--no-replace)')

    pkg, stored_total, n_toc = build_pkg(ordered, raw, start, repl, level=args.level,
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
    return 0


if __name__ == '__main__':
    sys.exit(main())
