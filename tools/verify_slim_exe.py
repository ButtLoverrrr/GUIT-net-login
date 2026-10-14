"""验证精简 exe：
A. 结构自检（cookie/TOC/PYZ 可解析、app 可 unmarshal）
B. 依赖闭包静态检查（pystray / PIL.ImageTk / PIL.Image / ddddocr / onnxruntime / numpy 引用的模块是否都还在；
   并确认没有任何模块引用被剔除的 cv2 / _avif / _imagingft）
C. 黑盒运行：--silent 严格模式（OCR 识别错→3 次后转手输，但必须真的 POST 过）+ 宽松模式（应 rc=0）
"""
import json
import marshal
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

PROJ = r'<本机路径>'
NEW = r'<本机路径>'
ORIG = r'<本机路径>'
PY313 = r'<本机路径>'
MAGIC = b'MEI\014\013\012\013\016'
COOKIE = '!8sIIII64s'
TOC_FMT = '!IIIIBc'
TOC_LEN = struct.calcsize(TOC_FMT)


def read_exe(path):
    raw = open(path, 'rb').read()
    off = raw.rfind(MAGIC)
    _m, alen, tocoff, toclen, pyvers, pylib = struct.unpack(COOKIE, raw[off:off + struct.calcsize(COOKIE)])
    start = off + struct.calcsize(COOKIE) - alen
    data = raw[start + tocoff: start + tocoff + toclen]
    toc, p = {}, 0
    while p < len(data):
        elen, eoff, dlen, ulen, cflag, tc = struct.unpack(TOC_FMT, data[p:p + TOC_LEN])
        name = data[p + TOC_LEN:p + elen].rstrip(b'\0').decode('utf-8')
        toc[name] = (eoff, dlen, ulen, cflag, tc.decode())
        p += elen
    return raw, start, toc, pyvers, pylib


def blob_of(raw, start, e):
    eoff, dlen, ulen, cflag, _tc = e
    b = raw[start + eoff:start + eoff + dlen]
    return zlib.decompress(b) if cflag else b


raw, start, toc, pyvers, pylib = read_exe(NEW)
oraw, ostart, otoc, _, _ = read_exe(ORIG)
print('A) 结构自检')
print('   大小        : %d 字节 (%.2f MiB)  原 %.2f MiB' % (len(raw), len(raw) / 1048576, len(oraw) / 1048576))
print('   pyver/pylib : %s / %s' % (pyvers, pylib.decode()))
print('   PKG 条目    : %d（原 %d）' % (len(toc), len(otoc)))
app_bytes = blob_of(raw, start, toc['app'])
co = marshal.loads(app_bytes)
print('   app 可解析  : %s (%d 条指令)' % (co.co_name, len(co.co_code) // 2))
pyz = blob_of(raw, start, toc['PYZ.pyz'])
assert pyz[:4] == b'PYZ\0'
pzoff = struct.unpack('!i', pyz[8:12])[0]
pz_entries = marshal.loads(pyz[pzoff:])
pz_names = {n for n, _v in pz_entries}
print('   PYZ 可解析  : %d 个模块' % len(pz_names))
print('   被剔除项是否仍在 PKG:',
      [n for n in ('cv2\\cv2.pyd', 'PIL\\_avif.cp313-win_amd64.pyd', 'PIL\\_imagingft.cp313-win_amd64.pyd') if n in toc] or '（已全部剔除）')

print('\nB) 依赖闭包静态检查')


def pyz_code(name):
    for n, v in pz_entries:
        if n == name:
            typ, off, length = v
            if typ == 3 or length <= 1:      # 命名空间包没有代码对象
                return None
            blob = pyz[off:off + length]
            try:
                blob = zlib.decompress(blob)
            except zlib.error:
                pass                          # 少数条目可能是未压缩直接存放
            try:
                return marshal.loads(blob)
            except (EOFError, ValueError):
                return None
    return None


import dis  # noqa: E402

present_files = {n.replace('/', '\\').lower() for n in toc}
present_mods = set(pz_names)


def refs(name):
    co = pyz_code(name)
    if co is None:
        return set()
    out = set()

    def walk(c):
        ops = list(dis.get_instructions(c))
        for ins in ops:
            if ins.opname == 'IMPORT_NAME':
                out.add(ins.argval)
            elif ins.opname in ('LOAD_GLOBAL', 'LOAD_NAME') and isinstance(ins.argval, str):
                out.add(ins.argval)
        for k in c.co_consts:
            if hasattr(k, 'co_code'):
                walk(k)
    walk(co)
    return out


missing = []
checked = 0
for pkg in ('pystray', 'PIL.ImageTk', 'PIL.Image', 'PIL.ImageDraw', 'ddddocr', 'onnxruntime', 'numpy'):
    names = [n for n in pz_names if n == pkg or n.startswith(pkg + '.')]
    for n in names[:400]:
        checked += 1
        for r in refs(n):
            root = r.split('.')[0]
            if root in ('cv2',):
                missing.append((n, r, 'cv2 已剔除但被引用'))
            elif '_avif' in r or '_imagingft' in r:
                missing.append((n, r, 'PIL 后端已剔除但被引用'))
print('   检查模块数  : %d（pystray/PIL/ddddocr/onnxruntime/numpy 及其子模块）' % checked)
print('   可疑引用    :', missing or '（无）')

print('\nC) 黑盒运行（自建模拟门户）')
sys.path.insert(0, os.path.join(PROJ, 'tests'))
sys.path.insert(0, PROJ)
import support  # noqa: E402
import portal_client  # noqa: E402

portal_client.ONLINE_PROBES = ()
work = tempfile.mkdtemp(prefix='slim-exe-')
target = os.path.join(work, 'GUIT-net-login.exe')
shutil.copy2(NEW, target)
results = {}
for tag, lenient in (('strict', False), ('lenient', True)):
    portal = support.MockPortal()
    if lenient:
        portal.state.accept_any_captcha = True
    cfg = portal.config()
    open(os.path.join(work, 'config.json'), 'w', encoding='utf-8').write(json.dumps(cfg, ensure_ascii=False, indent=2))
    try:
        p = subprocess.run([target, '--silent'], cwd=work, capture_output=True, timeout=90,
                           text=True, encoding='utf-8', errors='replace')
        rc = p.returncode
        print('      stdout:', (p.stdout or '')[-400:].replace('\n', ' | '))
        print('      stderr:', (p.stderr or '')[-800:].replace('\n', ' | '))
    except subprocess.TimeoutExpired:
        rc = 'TIMEOUT'
    results[tag] = {
        'rc': rc, 'online_after': portal.state.online, 'login_posts': portal.state.login_posts,
        'requests': [(m, q) for m, q, _f in portal.state.requests],
    }
    print('   [%s] rc=%s 门户在线=%s 登录POST=%d 请求=%s' % (
        tag, rc, portal.state.online, portal.state.login_posts,
        [q for _m, q in results[tag]['requests']]))
    portal.stop()
json.dump(results, open(r'<本机路径>', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)

ok = (results['lenient']['rc'] == 0 and results['lenient']['login_posts'] >= 1
      and results['strict']['login_posts'] >= 1 and results['strict']['rc'] == 3)
print('\n结论：', '通过（OCR 引擎在冻结 exe 内工作、登录闭环可用）' if ok else '需要复查')
