# OCR 接口层（解耦说明）

## 为什么要这层

界面（`src/app.py`）与登录流程（`portal_client.auto_login`）只需要两件事：

- 引擎可用吗？→ `available() -> bool`（不可用就回退「手动输入验证码」）
- 识别这张验证码 → `classify(png: bytes) -> str`（失败返回空串，不抛异常）

它们**不应该知道**背后是 ddddocr、自研 ONNX，还是根本没有 OCR。这层把这个边界固化成
契约 + 注册表，实现按名字装配。

## 结构

```
src/ocr.py           契约 + 注册表 + 按配置装配（不 import ddddocr）
  OcrBackend         抽象契约：available() / classify()
  NullBackend        显式关闭（name = "none"）：永远不可用、识别恒为空串
  register_backend() 注册实现：factory(length) -> OcrBackend
  create_backend()   按名字装配；未知名字 → NullBackend（安全降级，不打断主流程）
  backend_name_of()  从 config 读 options.ocrBackend（useOcr=False 等价于 none）
  create_engine()    业务代码用的唯一装配入口

src/ocr_helper.py    默认实现：ddddocr 后端（导入时注册名字 "ddddocr"）
src/app.py           build_ocr_engine(cfg) —— 全程序唯一装配点；
                     LoginApp(root, auto_connect, ocr=...) 支持注入（测试/未来替换）
portal_client.py     auto_login(cfg, logger, ocr=...) 只按契约调用（鸭子类型）
```

## 配置

```json
"options": {
  "useOcr": true,              // 历史总开关；false 一律等价于 ocrBackend = "none"
  "ocrBackend": "ddddocr"      // 缺省；可选 "none" 或任何已注册的名字
}
```

- `"ddddocr"`：默认，自动识别验证码。
- `"none"`：关闭自动识别，程序只用「手动输入」（与 `useOcr: false` 等价）。
- 未知名字：安全降级为 `none`，不会让程序报错或卡住。

## 接入自己的实现

1. 新建模块（例如 `src/my_ocr.py`），实现契约：

   ```python
   from ocr import OcrBackend, register_backend

   class MyBackend(OcrBackend):
       name = 'my'

       def __init__(self, length=4):
           self.CAPTCHA_LENGTH = length

       def available(self):
           return True          # 引擎可用（模型加载失败时返回 False，让界面回退手输）

       def classify(self, png):
           return '...'         # 识别结果；失败返回空串

   register_backend('my', lambda length=4: MyBackend(length), replace=True)
   ```

2. `config.json` 里设 `"ocrBackend": "my"`。
3. **打包时把新模块加进 `scripts/build.ps1` 的 `--hidden-import`**（实现是惰性导入的，
   静态分析看不到），并在 `scripts/check_bundle.py` 的 `RULES` 里加一条 required 断言，
   让它漏收就构建失败。

不需要改的是：`src/app.py`、`src/portal_client.py`、界面与重试逻辑。

## 约束（实现方必须遵守）

- `classify()` **不得抛异常**：任何失败都返回空串（上层据此回退手输）；
- `available()` 要能被多次并发调用（首次初始化可能耗时 1~2 秒，需自行加锁，
  参考 `ocr_helper.OcrEngine` 的实现）；
- 返回结果只保留字母数字并截断到 4 位（`ocr_helper` 现在做这一步；新实现若自行处理，
  请保持同样语义，界面按 4 位验证码设计）。
