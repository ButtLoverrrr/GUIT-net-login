# 诊断报告：连接 / 断开为什么一直失败（2026-10-13 实测）

被测项目：`Projects\GUIT-net-login`（源码 `src\portal_client.py`、`src\app.py`）
被测门户：`http://10.6.6.6`（ASP.NET WebForms，字段结构与 `config.json` 完全一致，非门户改版问题）

---

## 0. 一句话结论

**接口本身完全正确、账号也能登录成功**——实测真实凭据 `POST /login` 门户返回的是 `联网成功!`。
失败是**程序判定逻辑的 3 个缺陷**造成的：

| # | 缺陷 | 直接后果 |
| --- | --- | --- |
| 1 | `_judge()` 不认识门户的成功文案 `联网成功!`，只看「响应是否还是登录页」 | 真实登录成功被判失败，仅靠外网探测兜底；兜底一旦慢/被拦，就弹 `登录失败：联网成功!` |
| 2 | 注销前若发生过任何一次 `prepare()`（启动预取、点「换一张」），`hidden` 会被登录页 ViewState 覆盖，`submit_logoff()` 用它提交 | 门户返回 2530 字节**无提示空壳页**，程序报 `断开失败：门户未确认状态变化` |
| 3 | 同会话**重新取码会使旧码立即失效**（实测），而 GUI 的「预取码 / 输入框里的码」可能已过期 | 提交必然回 `验证码错误!`，表现为「连接失败 + 验证码错误」 |

外加一条易被忽略的环境项：

| 4 | `is_online()` 的兜底探测源是 `https://www.msftconnecttest.com/...`，本网络该地址 **TLS 被阻断**（curl 返回 000） | 在线判定偶发为 False，把成功的登录/断网判成失败 |

---

## 1. 证据链（全部实测，可复现）

### 1.1 真实凭据登录：门户明确回「联网成功!」，页面仍是登录页样式

`diagnose_guit.py` 用 `build\config.json` 里的真实账号提交（口令只打印长度）：

```
4) submit()（真实凭据 + OCR 验证码）
  ok=True | kind=ok | message=登录成功（联网探测确认）      ← 走了 is_online() 兜底
原始应答 03-POST-login.html（5426 字节）里的提示块：summary = 联网成功!
  同一页面仍含：验证码输入框 True | 登录按钮 True | 注销按钮 False
```

即：**门户登录成功的判据是 `validation-summary` 里的「联网成功!」，而不是「响应换了页面」**。
`_judge()` 现有实现（`portal_client.py:183`）把「仍是登录页」且文本不含 `验证码/密码/账号/锁定` 的情况归为 `KIND_UNKNOWN`，
于是成功被降级为未知，只能靠 `submit()` 末尾的 `is_online()` 兜底救回——用户看到的 `登录失败：联网成功!` 就是兜底也失败时的文案。

### 1.2 ViewState 错配：注销必然失败

`probe_logoff_mismatch.py` 的 A 组：

```
用「登录页的 ViewState」POST /logoff + 错码
  → HTTP 200 | 2530 字节 | 无特征（无提示块、无注销按钮、无登录按钮）| 提示文本 ''
用「注销页自身的 ViewState」POST /logoff + 错码
  → HTTP 200 | 4059 字节 | 含验证码输入框、含注销按钮        | 提示文本 '验证码错误!'
```

登录页与注销页的隐藏字段不同（`__VIEWSTATE` 368 / 328，`__EVENTVALIDATION` 328 / 240），**不能互换**。
程序里 `prepare()`（取登录页）会把 `self.hidden` 覆盖，而 `captcha_purpose` 仍可能停在 `logoff`，此时点「断开网络」就会走到错配分支，
门户给空壳页 → `submit_logoff()` 走到最后 `_confirm_offline(..., fallback="断开失败：门户未确认状态变化")` → **用户看到的就是这条**。

触发路径（代码位置）：

- `app.py:690` `_refresh_worker()` → `self.session.prepare()`（点「换一张」或刷新验证码）
- `app.py:777` `_prefetch_worker()` → `self.session.prepare()`（每次启动/预取）
- 两者都在用户已经进入「注销流程」之后仍可能执行。

### 1.3 叠码即失效，预取的码可能已经作废

`probe_logoff_mismatch.py` 的 B 组（同会话连续取两张码）：

```
第一张 OCR='tlbc' → 提交 → '验证码错误!'
第二张 OCR='Mjns' → 提交 → '用户未实名注册运营商上网账号!'
```

结论：**同一会话取新码会让上一张立即失效**（不是「可复用」）。
程序在启动时预取码#1 并 OCR 填进输入框，用户稍后点「连接」时若中间发生过任何一次取码，码#1 已作废 → 必然返回 `验证码错误!`。

### 1.4 在线探测源在本网络不可靠

```
http://www.msftconnecttest.com/connecttest.txt      → 200（22 字节，内容正确）
https://www.msftconnecttest.com/connecttest.txt     → 000（TLS 被阻断）
https://connectivitycheck.gstatic.com/generate_204  → 000
http://www.gstatic.com/generate_204                 → 204
https://www.baidu.com / http://www.baidu.com        → 200
```

`portal_client.py:110` 的兜底默认值是 **https** 的 msftconnecttest；`config.json` 里虽是 http（当前可用），但该域名偶发慢/被拦时，
`is_online()` 会返回 False —— 直接影响：登录成功兜底失败（缺陷 1 的放大）、注销后 12 秒探测期误判。

---

## 2. 修复补丁（可直接应用，逐项独立）

### 2.1 `src\portal_client.py`：`_judge()` 先认门户成功文案

```python
# 类常量：门户在 validation-summary 里给出的成功文案（实测登录成功 = 「联网成功!」）
SUCCESS_WORDS = ("联网成功", "登录成功", "断开成功", "注销成功", "成功")

def _judge(self, html: str) -> LoginResult:
    """按响应内容判定成败并分类。

    关键：本门户 **登录成功时仍然渲染登录页样式**（含验证码框与登录按钮），
    只在 validation-summary 里写「联网成功!」。因此必须先认成功文案，
    否则真实成功会被降级为 KIND_UNKNOWN，只能靠外网探测兜底。
    """
    text = self._extract_error(html)
    if text and "验证码" not in text and any(w in text for w in self.SUCCESS_WORDS):
        return LoginResult(True, text, KIND_OK)

    names = self.cfg["fields"]
    still_login_page = (names["captcha"] in html or names["submit"] in html)
    if still_login_page:
        if "验证码" in text:
            kind = KIND_CAPTCHA
        elif "密码" in text or "账号" in text or "锁定" in text:
            kind = KIND_CREDENTIAL
        else:
            kind = KIND_UNKNOWN
        return LoginResult(False, text or "登录失败（门户返回登录页）", kind)
    return LoginResult(True, "登录成功", KIND_OK)
```

### 2.2 `src\portal_client.py`：隐藏字段带「来源页面」标记，杜绝 ViewState 错配

```python
# __init__ 里新增
self.form_source = ""      # "login" / "logoff"：current hidden/defaults 来自哪个页面

# open_session() 末尾新增
self.form_source = "login"

# prepare_logoff() 末尾（return 之前）新增
self.form_source = "logoff"

# submit_logoff() 开头新增
def submit_logoff(self, captcha: str) -> LoginResult:
    if self.form_source != "logoff":
        # 中途调用过 prepare()（预取 / 换一张），ViewState 已被登录页覆盖；
        # 用它提交只会拿到门户的无提示空壳页（实测 2530 字节）。重新取注销页，
        # 并按 KIND_CAPTCHA 让界面刷新验证码后重试。
        self.prepare_logoff()
        return LoginResult(False, "注销页状态已刷新，请重新输入验证码", KIND_CAPTCHA)
    ...
```

### 2.3 `src\portal_client.py`：验证码 epoch，避免用已作废的码提交

```python
# __init__ 里新增
self.captcha_epoch = 0          # 每取一次验证码 +1

# fetch_captcha() 与 prepare_logoff() 里，成功取到 PNG 后各加一行
self.captcha_epoch += 1
```

`src\app.py` 对应改动：

```python
# _handle() 的 "captcha" 分支：记住「当前显示的这张码」属于哪个 epoch
elif kind == "captcha":
    self._show_captcha(args[0])
    self.var_captcha.set(args[1] if len(args) > 1 and args[1] else "")
    if self.session is not None:
        self.captcha_epoch = self.session.client.captcha_epoch

# 新增属性（__init__）：self.captcha_epoch = -1

# _on_connect() 里，取用输入框验证码之前先校验 epoch
current = self.session.client.captcha_epoch if self.session is not None else -1
manual = "" if (self.captcha_purpose == "logoff" or current != self.captcha_epoch) \
         else self.var_captcha.get().strip()
```

### 2.4 `src\portal_client.py`：`is_online()` 多源降级

```python
# 类常量
ONLINE_PROBES = (
    ("http://www.msftconnecttest.com/connecttest.txt", "Microsoft Connect Test"),
    ("http://www.gstatic.com/generate_204", ""),
    ("https://www.baidu.com", "baidu"),
    ("http://www.baidu.com", "baidu"),
)

def is_online(self) -> bool:
    """多源降级探测：任一命中即视为已联网。

    本网络实测 https://www.msftconnecttest.com 与
    https://connectivitycheck.gstatic.com 均被阻断（TLS 000），
    只用单一 HTTPS 源会把「已联网」判成离线。
    """
    probe = self.cfg.get("onlineProbe") or {}
    candidates = []
    if probe.get("url"):
        candidates.append((probe["url"], probe.get("expect", "")))
    candidates += list(self.ONLINE_PROBES)

    for url, expect in candidates:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=int(probe.get("timeout", 4) or 4)) as resp:
                if expect:
                    if expect in resp.read(256).decode("utf-8", "ignore"):
                        return True
                elif resp.status == 204:
                    return True
        except Exception:
            continue
    return False
```

### 2.5（可选）`src\app.py`：`--silent` 失败文案不要吞掉门户原话

`run_silent()` 现在是 `toast("登录失败：%s" % result.message)`；修完 2.1 后 `message` 不会再是「联网成功!」，但建议补一条防御：

```python
    if not result.ok and any(w in (result.message or "") for w in ("成功",)):
        # 门户说成功、本程序却判失败：提示改口径，避免误导
        toast("连接状态待确认：%s\n可点「连接」重试一次" % result.message, error=True)
        return 1
```

---

## 3. 复现与验证命令

```powershell
# 真实凭据链路诊断（会真实登录一次，无破坏性；口令只打印长度）
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
& '.venv\Scripts\python.exe' '<探针目录>\diagnose_guit.py'

# 缺陷 2/3 的无损复现（不提交正确验证码，不会真的断网）
& '.venv\Scripts\python.exe' '<探针目录>\probe_logoff_mismatch.py'
```

原始应答留档：`<探针目录>\diag\`（`03-POST-login.html` 即门户的「联网成功!」页）。

## 4. 修复后的验收清单（需真实断网，建议你本人执行）

1. 断网状态下点「连接」→ 期望：日志出现 `联网成功!`，状态栏转「已联网」；不再出现 `登录失败：联网成功!`。
2. 先点「断开网络」→ 拿到验证码 →**故意点一次「换一张」** → 再输码点「断开网络」→ 期望：不再出现 `断开失败：门户未确认状态变化`，要么提示「注销页状态已刷新，请重新输入验证码」，要么直接断开成功。
3. 联网状态下点「连接」→ 期望：仍提示「网络已连通，无需登录」（幂等）。
4. `--autostart` 冷启动（断网状态）→ 期望：自动打开界面并自动连接（最多重试 3 次、间隔 12 秒），
   日志出现「开机自动登录：正在连接（第 1/3 次）」与 `联网成功!`。

## 5. 修复实施记录（2026-10-13 19:05，经用户批准后执行）

| 项 | 内容 |
| --- | --- |
| 备份 | `temp\output\backup-20261013\`：原 `portal_client.py`、`app.py`、`config.json`、`CHANGELOG.md`、旧 exe |
| 改动 | `src\portal_client.py`：`_judge()` 先认成功文案（`SUCCESS_WORDS`）、`form_source` 守卫、`captcha_epoch`、`is_online()` 多源降级、新增 `refresh_portal_status()` 并让 `_confirm_offline()` 门户状态优先 |
| 改动 | `src\app.py`：`captcha_epoch` 记录与提交前校验、`_logoff_worker` 的 ready 三重判定、`_refresh_status()` 与「断开前是否已离线」改为门户状态优先 |
| 静态 | `.venv\Scripts\python.exe -m py_compile src\portal_client.py src\app.py` → 通过 |
| 无损验证 | ViewState 错配提交被拒（`kind=captcha`、提示重新输码）；epoch `0→1→2`；首选探测源不可达时 `is_online=True`（1.12 秒降级成功） |
| 登录终验 | 真实凭据 → `ok=True | message=联网成功!`（不再依赖外网探测兜底） |
| 注销终验 | `ok=True | 已断开网络（门户已确认下线）`，**耗时 0.06 秒**（旧实现 13.6 秒） |
| 重连终验 | 第 1 次 OCR 错 → 自动换码；第 2 次 `联网成功!`，门户状态回到 `已联网` |
| 打包 | `scripts\build.ps1 -Target all` → `build\GUIT-net-login-full.exe`、`build\GUIT-net-login-lite.exe` |

### 5.1 追加发现的缺陷 5（已修）

**「断开」的判据原本用错了**，这是"断开一直失败"的最后一块拼图：

- 实测本机注销后门户状态**立刻**变 `未联网`，但**外网依旧可达**（出口另有旁路通道）；
- 旧逻辑以「外网是否可达」判断开 → 永远得到"未生效"，于是报 `断开失败`／`生效略有延迟`；
- 旧逻辑还只读 **POST 响应页**里的状态，而那一页渲染的是**提交前**的旧值（实测仍写 `已联网`）；
- 修复后：注销 → 重新 `GET /logoff` 读状态 → `未联网` → 立即判成功。

### 5.2 网络侧现实（非程序缺陷，需要你知道）

这台机器的**出口连接不由该门户会话控制**：提交注销后门户已显示 `未联网`，但外网仍可访问
（60 秒观察窗内一直可达）。因此「断开网络」在你这套网络形态下**不会真的切断出口**——
门户侧的会话被注销了，实际放行由别的机制维持（路由器 / 其他设备 / 其他认证通道）。
程序现在的行为是如实报告（`门户已确认下线；本机外网仍可达…`），不再谎报失败。
