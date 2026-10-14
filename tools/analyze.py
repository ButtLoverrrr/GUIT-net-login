"""全局结构/调用链静态分析：直接读 exe 内原始 marshal 代码对象，产出 docs/STRUCTURE.md。

不执行程序、不依赖反编译文本，结论可直接作为评审证据。
"""
import dis
import marshal
import os
import re
import sys
from collections import OrderedDict, defaultdict

ROOT = r'<本机路径>'
MAR = os.path.join(ROOT, 'work', 'marshal')
OUT = os.path.join(r'<本机路径>', 'docs', 'STRUCTURE.md')
MODULES = ['app', 'portal_client', 'config_store', 'ocr_helper', 'app_logger', 'autostart']


def walk(co, path, acc):
    acc.append((path, co))
    for c in co.co_consts:
        if hasattr(c, 'co_code'):
            walk(c, f'{path}.{c.co_name}', acc)
    return acc


def calls_of(co):
    """粗粒度调用名集合：CALL 之前压栈的全局/属性名。"""
    names, ops = [], list(dis.get_instructions(co))
    for i, ins in enumerate(ops):
        if ins.opname in ('CALL', 'CALL_KW', 'CALL_FUNCTION_EX'):
            window = [o for o in ops[max(0, i - 8):i]]
            labels = [o.argval for o in window if o.opname in ('LOAD_GLOBAL', 'LOAD_ATTR', 'LOAD_NAME', 'LOAD_METHOD')]
            names.append('.'.join(str(x) for x in labels[-2:]) if labels else '?')
    return names


def strings_of(co, limit=6):
    out = []
    for c in co.co_consts:
        if isinstance(c, str) and c and not c.startswith('\n'):
            out.append(c.replace('\n', ' / ')[:60])
        if hasattr(c, 'co_consts'):
            for cc in c.co_consts:
                if isinstance(cc, str) and len(cc) > 8 and not cc.startswith('\n'):
                    out.append(cc.replace('\n', ' / ')[:60])
    seen, res = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            res.append(s)
    return res[:limit]


lines = ['# 代码结构与调用链静态分析（原始字节码级）', '',
         '> 数据来源：exe 内 PyInstaller PYZ 的原始 marshal 代码对象（CPython 3.13），',
         '> 由 `guit-re/analyze.py` 静态提取，不执行程序。', '']

imports_all = {}
inventory = OrderedDict()
for mod in MODULES:
    co = marshal.loads(open(os.path.join(MAR, mod + '.marshal'), 'rb').read())
    funcs = walk(co, mod, [])
    inventory[mod] = funcs
    imps = [i.argval for i in dis.get_instructions(co) if i.opname == 'IMPORT_NAME']
    imports_all[mod] = imps

lines += ['## 模块规模与导入', '', '| 模块 | 代码对象数 | 指令总数 | 顶层 import |', '|---|---|---|---|']
for mod, funcs in inventory.items():
    ninstr = sum(len(co.co_code) // 2 for _, co in funcs)
    lines.append(f'| `{mod}.py` | {len(funcs)} | {ninstr} | {", ".join("`%s`" % i for i in imports_all[mod]) or "—"} |')

lines += ['', '## 函数清单（含指令数 / 起始行 / 内部调用）', '']
for mod, funcs in inventory.items():
    lines += [f'### {mod}.py', '', '| 函数 | 起始行 | 指令数 | 关键调用 |', '|---|---|---|---|']
    for path, co in funcs:
        name = path.split('.', 1)[1] if '.' in path else '<module>'
        cs = sorted(set(calls_of(co)))
        cs = [c for c in cs if c not in ('?',)][:6]
        lines.append(f'| `{name}` | {co.co_firstlineno} | {len(co.co_code)//2} | {", ".join(cs) or "—"} |')
    lines.append('')

# 跨模块调用边（按 co_names 中的函数名与 import 关系推断）
KNOWN = {
    'portal_client': {'LoginSession', 'PortalClient', 'auto_login', 'PortalError', 'LoginResult', 'PortalStatus'},
    'config_store': {'load_config', 'save_config', 'remove_config', 'has_credential', 'app_dir', 'config_path'},
    'ocr_helper': {'OcrEngine'},
    'app_logger': {'Logger'},
    'autostart': {'is_enabled', 'enable', 'disable', 'ensure_current', 'read_lnk', 'startup_dir'},
}
lines += ['## 跨模块调用边（静态）', '']
for mod, funcs in inventory.items():
    edges = defaultdict(set)
    for path, co in funcs:
        for owner, names in KNOWN.items():
            if owner == mod:
                continue
            for n in names:
                if n in co.co_names:
                    edges[owner].add(n)
    for owner, names in edges.items():
        lines.append(f'- `{mod}` → `{owner}`：{", ".join(sorted(names))}')
    lines.append('')

lines += ['## 关键流程的事实依据（从字节码提取的字符串/常量）', '']
for mod in ('app', 'portal_client', 'config_store', 'autostart', 'ocr_helper'):
    co = marshal.loads(open(os.path.join(MAR, mod + '.marshal'), 'rb').read())
    lines += [f'### {mod}', '']
    for path, c in walk(co, mod, []):
        s = strings_of(c)
        if s:
            lines.append(f'- `{path.split(".", 1)[1] if "." in path else "<module>"}`: ' + ' ｜ '.join(s))
    lines.append('')

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, 'w', encoding='utf-8').write('\n'.join(lines))
print('written', OUT, len(lines), 'lines')
print('\n'.join(lines[:40]))
