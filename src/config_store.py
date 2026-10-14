'''配置读写：**单文件、便携语义**。

配置文件固定为程序同目录下的 `config.json`（不建子目录），仅在用户勾选了
「记住密码」或「开机自动登录」时才创建；两者都不勾选时该文件会被删除，
因此程序在不记忆任何信息的情况下不会遗留文件。
'''

import json
import os
import sys
CONFIG_FILE_NAME = 'config.json'
DEFAULT_CONFIG = {'portalUrl': 'http://10.6.6.6/login', 'portalHome': 'http://10.6.6.6', 'captchaUrl': 'http://10.6.6.6/CheckCode', 'submitUrl': 'http://10.6.6.6/login', 'logoffUrl': 'http://10.6.6.6/logoff', 'fields': {'guid': 'ctl00$MainContent$SSOGUITID', 'acc': 'ctl00$MainContent$SSOACC', 'pwd': 'ctl00$MainContent$SSOPWD', 'captcha': 'ctl00$MainContent$TextBoxCC', 'submit': 'ctl00$MainContent$LoginBtn'}, 'submitValue': '登录', 'logoffFields': {'captcha': 'ctl00$MainContent$TextBoxCC', 'submit': 'ctl00$MainContent$LogoffBtn', 'submitValue': '注销'}, 'statusFields': {'ip': 'MainContent_LocalIP', 'online': 'MainContent_LabelOnline'}, 'user': {'guid': '', 'acc': '', 'pwd': ''}, 'options': {'remember': True, 'autostart': False, 'useOcr': True}, 'maxCaptchaRetry': 3, 'onlineProbe': {'url': 'http://www.msftconnecttest.com/connecttest.txt', 'expect': 'Microsoft Connect Test', 'timeout': 4}}

def app_dir() -> str:
    '''程序所在目录：打包运行时是 exe 所在目录，开发运行时是项目根目录。'''

    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def config_path() -> str:
    '''配置文件路径：程序同目录下的单个 config.json（不建子目录）。'''

    return os.path.join(app_dir(), CONFIG_FILE_NAME)

def _merge(base: dict, override: dict) -> dict:
    '''浅层合并：以 base 为骨架，用 override 覆盖同名键（嵌套 dict 递归一层）。'''

    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            merged = dict(out[key])
            merged.update(value)
            out[key] = merged
        else:
            out[key] = value
    return out

def load_config() -> dict:
    '''读取配置；文件缺失或损坏时返回默认配置（不抛异常，保证程序能启动）。'''

    try:
        with open(config_path(), 'r', encoding='utf-8') as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            raise ValueError('配置根节点必须是对象')
        return _merge(DEFAULT_CONFIG, data)
    except Exception:
        return dict(DEFAULT_CONFIG)

def save_config(cfg: dict) -> None:
    '''保存配置（UTF-8 无 BOM、结尾换行）到程序同目录的 config.json。

    原子替换：先写同目录临时文件，再 os.replace 覆盖目标。直接覆盖写的话，
    断电 / 磁盘满 / 进程被杀会留下半截 JSON，下次启动 load_config 只能整体
    退回默认值——用户填过的账号密码就凭空丢了。
    '''

    path = config_path()
    tmp = '%s.tmp' % path
    try:
        with open(tmp, 'w', encoding='utf-8') as fp:
            json.dump(cfg, fp, ensure_ascii=False, indent=2)
            fp.write('\n')
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise

def remove_config() -> bool:
    '''删除本地配置文件；返回是否确实删除（用于「不留痕迹」场景）。'''

    try:
        path = config_path()
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False

def has_credential(cfg: dict) -> bool:
    '''是否已填写完整登录信息：学号 + 上网账号（手机号） + 密码。

    上网账号对应门户 SSOACC 字段，是真正用于认证的账号，不能省略。
    '''

    user = cfg.get('user')
    if not isinstance(user, dict):
        user = {}
    # 缺键 / 值非字符串都要安全退化成「不完整」：手改 config.json 把值写成对象时，
    # 旧写法 `user.get(key)(''.strip())` 会抛不可调用异常。只有三个键都是非空字符串
    # 才算填完整（数字/对象等异类值一律按「没填」处理）。
    return all(isinstance(user.get(key), str) and bool(user.get(key).strip())
               for key in ('guid', 'acc', 'pwd'))
