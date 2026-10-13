# -*- coding: utf-8 -*-
"""配置读写：便携语义 —— 配置始终位于程序所在目录。

打包为 exe 后，程序目录即 exe 所在目录，因此 config/config.json 可随 exe
一起复制到任意机器（符合「portable 软件」的分发要求）。
"""

import json
import os
import sys

CONFIG_DIR_NAME = "config"
CONFIG_FILE_NAME = "config.json"

# 默认配置：字段名映射按 10.6.6.6 门户（ASP.NET WebForms）实测结构固化，
# 若门户改版，只需改这里或 config.json，无需改代码。
DEFAULT_CONFIG = {
    "portalUrl": "http://10.6.6.6/login",
    "portalHome": "http://10.6.6.6",
    "captchaUrl": "http://10.6.6.6/CheckCode",
    "submitUrl": "http://10.6.6.6/login",
    "logoffUrl": "http://10.6.6.6/logoff",
    "fields": {
        "guid": "ctl00$MainContent$SSOGUITID",
        "acc": "ctl00$MainContent$SSOACC",
        "pwd": "ctl00$MainContent$SSOPWD",
        "captcha": "ctl00$MainContent$TextBoxCC",
        "submit": "ctl00$MainContent$LoginBtn",
    },
    "submitValue": "登录",
    # 注销（断开网络）表单字段：与登录页共用验证码输入框名，提交按钮不同
    "logoffFields": {
        "captcha": "ctl00$MainContent$TextBoxCC",
        "submit": "ctl00$MainContent$LogoffBtn",
        "submitValue": "注销",
    },
    # 状态解析：注销页上的「当前用户IP」与「当前在线状态」两个 span 的 id
    "statusFields": {
        "ip": "MainContent_LocalIP",
        "online": "MainContent_LabelOnline",
    },
    "user": {"guid": "", "acc": "", "pwd": ""},
    "options": {
        "remember": True,
        "autostart": False,
        "useOcr": True,
    },
    "maxCaptchaRetry": 3,
    "onlineProbe": {
        "url": "http://www.msftconnecttest.com/connecttest.txt",
        "expect": "Microsoft Connect Test",
        "timeout": 4,
    },
}


def app_dir() -> str:
    """程序所在目录：打包运行时是 exe 所在目录，开发运行时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_dir() -> str:
    return os.path.join(app_dir(), CONFIG_DIR_NAME)


def config_path() -> str:
    return os.path.join(config_dir(), CONFIG_FILE_NAME)


def log_dir() -> str:
    return os.path.join(app_dir(), "logs")


def _merge(base: dict, override: dict) -> dict:
    """浅层合并：以 base 为骨架，用 override 覆盖同名键（嵌套 dict 递归一层）。"""
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
    """读取配置；文件缺失或损坏时返回默认配置（不抛异常，保证程序能启动）。"""
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            raise ValueError("配置根节点必须是对象")
        return _merge(DEFAULT_CONFIG, data)
    except FileNotFoundError:
        return dict(DEFAULT_CONFIG)
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    """保存配置（UTF-8 无 BOM），目录不存在则创建。"""
    os.makedirs(config_dir(), exist_ok=True)
    with open(config_path(), "w", encoding="utf-8") as fp:
        json.dump(cfg, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def has_credential(cfg: dict) -> bool:
    """是否已填写完整登录信息：学号 + 上网账号（手机号） + 密码。

    上网账号对应门户 SSOACC 字段，是真正用于认证的账号，不能省略。
    """
    user = cfg.get("user") or {}
    return all(bool((user.get(key) or "").strip()) for key in ("guid", "acc", "pwd"))
