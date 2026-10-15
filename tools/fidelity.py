"""反编译保真度校验 v2（严格版）。

把反编译源码用 3.13 重新编译，与 exe 内原始 marshal 代码对象逐层比对：
  - 强校验：指令序列（opname + 语义化 argval；跳转目标规范化为指令序号）
  - 强校验：co_names / co_varnames / co_argcount / co_flags
  - 弱校验：常量集合（只报"一边有另一边没有"）
  - 忽略：__firstlineno__、行号、co_firstlineno（反编译后行号必然不同）

用法: <本机路径>
退出码 0 = 全部一致；1 = 有差异
"""
import dis, marshal, os, sys

ROOT = r'<本机路径>'
PROJ = sys.argv[1] if len(sys.argv) > 1 else os.path.join(r'<本机路径>', 'guit-net-login')
MAR = os.path.join(ROOT, 'work', 'marshal')
# 用途说明（2026-10-15 OCR 解耦后）：与**反编译基线**（work\marshal，未入库）逐指令
# 比对，因此清单只包含基线里存在的模块——`ocr.py` 是解耦时新增的，基线中不存在，
# 加进来只会得到「缺少原始 marshal（跳过）」。新增模块的结构检查由 tests 负责。
MODULES = ['app', 'portal_client', 'config_store', 'ocr_helper', 'app_logger', 'autostart']

SKIP_OPS = {'RESUME', 'CACHE', 'NOP', 'EXTENDED_ARG', 'PRECALL', 'COPY_FREE_VARS', 'MAKE_CELL', 'RETURN_GENERATOR'}
JUMP_PREFIX = ('POP_JUMP', 'JUMP', 'FOR_ITER', 'SEND', 'END_ASYNC_FOR')


def norm_instrs(co):
    """规范化指令序列：跳转目标→指令序号；剔除行号噪声。"""
    raw = list(dis.get_instructions(co))
    off2idx = {ins.offset: i for i, ins in enumerate(raw)}
    out = []
    for ins in raw:
        if ins.opname in SKIP_OPS:
            continue
        arg = ins.argval
        if hasattr(arg, 'co_code'):
            arg = '<code %s>' % arg.co_name
        if ins.opname.startswith(JUMP_PREFIX):
            arg = ('->idx', off2idx.get(arg, arg))
        out.append((ins.opname, arg if isinstance(arg, (int, str, type(None), bool, float, tuple)) else repr(arg)))
    # 剔除 __firstlineno__ 及紧随其前的 LOAD_CONST
    cleaned = []
    i = 0
    while i < len(out):
        if out[i] == ('STORE_NAME', '__firstlineno__'):
            if cleaned and cleaned[-1][0] == 'LOAD_CONST':
                cleaned.pop()
            i += 1
            continue
        cleaned.append(out[i])
        i += 1
    return cleaned


def cmp_consts(oc, nc):
    oc = [c for c in oc if not hasattr(c, 'co_code')]
    nc = [c for c in nc if not hasattr(c, 'co_code')]
    miss = [c for c in oc if c not in nc]
    extra = [c for c in nc if c not in oc]
    return miss, extra


def compare(orig, new, path, report):
    if orig.co_argcount != new.co_argcount:
        report.append(f'{path}: co_argcount {orig.co_argcount} -> {new.co_argcount}')
    if orig.co_names != new.co_names:
        report.append(f'{path}: co_names 差异\n      orig={orig.co_names}\n      new ={new.co_names}')
    if orig.co_varnames != new.co_varnames:
        report.append(f'{path}: co_varnames 差异\n      orig={orig.co_varnames}\n      new ={new.co_varnames}')
    if orig.co_flags != new.co_flags:
        report.append(f'{path}: co_flags {orig.co_flags:#x} -> {new.co_flags:#x}')
    for attr in ('co_freevars', 'co_cellvars'):
        if getattr(orig, attr) != getattr(new, attr):
            report.append(f'{path}: {attr} {getattr(orig, attr)} -> {getattr(new, attr)}')
    a, b = norm_instrs(orig), norm_instrs(new)
    if a != b:
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                lo = max(0, i - 3)
                report.append(f'{path}: 指令分歧 @#{i}\n      orig={a[lo:i + 3]}\n      new ={b[lo:i + 3]}')
                break
        if len(a) != len(b):
            report.append(f'{path}: 指令条数 {len(a)} -> {len(b)}')
    miss, extra = cmp_consts(orig.co_consts, new.co_consts)
    if miss or extra:
        report.append(f'{path}: 常量集合差异\n      仅原始有={miss}\n      仅反编译有={extra}')
    ocodes = {c.co_name: c for c in orig.co_consts if hasattr(c, 'co_code')}
    ncodes = {c.co_name: c for c in new.co_consts if hasattr(c, 'co_code')}
    for name in ocodes:
        if name not in ncodes:
            report.append(f'{path}.{name}: 新代码中缺失')
        else:
            compare(ocodes[name], ncodes[name], f'{path}.{name}', report)
    for name in ncodes:
        if name not in ocodes:
            report.append(f'{path}.{name}: 新代码中多出')


lines, total = [], 0
for mod in MODULES:
    mp, sp = os.path.join(MAR, mod + '.marshal'), os.path.join(PROJ, mod + '.py')
    if not os.path.exists(mp):
        lines.append(f'### {mod}: 缺少原始 marshal（跳过）')
        continue
    orig = marshal.loads(open(mp, 'rb').read())
    src = open(sp, encoding='utf-8').read()
    try:
        new = compile(src, orig.co_filename, 'exec')
    except SyntaxError as e:
        lines.append(f'### {mod}: 语法错误 line {e.lineno}: {e.msg}')
        total += 1
        continue
    rep = []
    compare(orig, new, mod, rep)
    total += len(rep)
    lines.append(f'### {mod}: 差异项 {len(rep)}')
    lines += ['  - ' + r for r in rep]
    lines.append('')

lines.append(f'=== 总计差异项: {total} ===')
text = '\n'.join(lines)
print(text)
open(os.path.join(ROOT, 'fidelity_report.txt'), 'w', encoding='utf-8').write(text)
sys.exit(1 if total else 0)
