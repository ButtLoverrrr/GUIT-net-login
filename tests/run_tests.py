"""统一测试入口（零第三方依赖）。

用法:
    tools\\py313\\python.exe tests\\run_tests.py [backend|gui|perf|all]
退出码 0 = 全部通过；1 = 有失败。
"""
import importlib
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, PROJ)
# 仓库布局：第一方模块在 src/ 子目录（原工作区在项目根，两种都兼容）
_SRC = os.path.join(PROJ, 'src')
if os.path.isdir(_SRC):
    sys.path.insert(0, _SRC)


def run(module_name, only=None):
    mod = importlib.import_module(module_name)
    names = [n for n in dir(mod) if n.startswith('test_')]
    if only:
        names = [n for n in names if any(o in n for o in only)]
    passed, failed = 0, []
    for name in sorted(names):
        fn = getattr(mod, name)
        if not callable(fn):
            continue
        try:
            fn()
            print(f'  PASS  {module_name}.{name}')
            passed += 1
        except Exception:
            print(f'  FAIL  {module_name}.{name}')
            traceback.print_exc()
            failed.append(f'{module_name}.{name}')
        sys.stdout.flush()
    return passed, failed


def main():
    which = (sys.argv[1] if len(sys.argv) > 1 else 'all').lower()
    only = sys.argv[2:] or None
    total_passed, total_failed = 0, []
    if which in ('all', 'backend'):
        print('== 后端 ==')
        p, f = run('test_backend', only)
        total_passed += p
        total_failed += f
    if which in ('all', 'gui'):
        print('== 前端 / 界面 ==')
        p, f = run('test_gui', only)
        total_passed += p
        total_failed += f
    if which in ('all', 'silent'):
        print('== 静默模式 ==')
        p, f = run('test_silent', only)
        total_passed += p
        total_failed += f
    if which in ('all', 'layout'):
        print('== 界面布局（不裁切） ==')
        p, f = run('test_layout', only)
        total_passed += p
        total_failed += f
    if which in ('all', 'instance'):
        print('== 单实例行为 ==')
        p, f = run('test_instance', only)
        total_passed += p
        total_failed += f
    if which in ('all', 'perf'):
        print('== 性能 ==')
        p, f = run('test_perf', only)
        total_passed += p
        total_failed += f
    print(f'\n通过 {total_passed} 项，失败 {len(total_failed)} 项')
    for name in total_failed:
        print('  FAILED:', name)
    return 1 if total_failed else 0


if __name__ == '__main__':
    sys.exit(main())
