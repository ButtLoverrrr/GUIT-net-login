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
  create_engine()    按配置装配（create_backend(backend_name_of(cfg))）
  safe_available()   available() 的安全包装：实现方抛异常 → False
  safe_classify()    classify() 的安全包装：实现方抛异常 → 空串
  _LOADERS           名字 → 实现模块；**唯一的惰性加载入口**

src/ocr_helper.py    默认实现：ddddocr 后端（导入时注册名字 "ddddocr"）
src/app.py           build_ocr_engine(cfg) —— 全程序唯一装配点；
                     LoginApp(root, auto_connect, ocr=...) 支持注入（测试/未来替换）
portal_client.py     auto_login(cfg, logger, ocr=...) 只按契约调用（鸭子类型）
```

调用链：`app` / `portal_client` → `ocr`（契约 + 装配） → `ocr_helper`（默认实现）
→ `ddddocr`。业务代码不 import `ocr_helper`，也不 import `ddddocr`。

## 配置

```json
"options": {
  "useOcr": true,              // 历史总开关；false 一律等价于 ocrBackend = "none"
  "ocrBackend": "ddddocr"      // 缺省；可选 "none" 或任何已在 _LOADERS 登记的名字
}
```

- `"ddddocr"`：默认，自动识别验证码。
- `"none"`：关闭自动识别，程序只用「手动输入」（与 `useOcr: false` 等价）。
- 未知名字：安全降级为 `none`，不会让程序报错或卡住。
- **配置类型保护**（手改 `config.json` 不会让程序崩）：
  - `cfg` / `options` 不是对象 → 按空配置处理（取默认后端）；
  - `ocrBackend` 是空串或纯空白 → 视为未配置，取默认 `ddddocr`；
  - `ocrBackend` 不是字符串（数字、对象、列表等）→ 按 `none` 处理：
    非法配置**不会**回退到默认 ddddocr，避免手改错类型时意外拉起重量级 OCR。

## 接入自己的实现（`_LOADERS` 是唯一的惰性加载入口）

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

2. **在 `src/ocr.py` 的 `_LOADERS` 里登记 `'my': 'my_ocr'`**。这一步不可省：
   `create_backend('my')` 只会按 `_LOADERS` 里的模块名去惰性导入，导入该模块时
   `register_backend()` 才执行、名字才真正可用。没有登记 → 按未知名字处理 →
   安全降级成 `none`（只用手输），**不会**自动扫描目录或自动导入任何文件。
3. `config.json` 里设 `"ocrBackend": "my"`。
4. **打包时把新模块加进 `scripts/build.ps1` 的 `--hidden-import`**，并在
   `scripts/check_bundle.py` 的 `RULES` 里加一条 required 断言，让它漏收就构建失败。
   - `--hidden-import` 的职责只有一个：**把模块打进包**；
   - 它**不负责运行时自动导入**——触发导入的永远是 `_LOADERS` 登记 + `create_backend()`。

不需要改的是：`src/app.py`、`src/portal_client.py`、界面与重试逻辑。

## 约束（实现方必须遵守）

- `classify()` **不得抛异常**：任何失败都返回空串（上层据此回退手输）；
- `available()` 要能被多次并发调用（首次初始化可能耗时 1~2 秒，需自行加锁，
  参考 `ocr_helper.OcrEngine` 的实现）；
- 返回结果只保留字母数字并截断到 4 位（`ocr_helper` 现在做这一步；新实现若自行处理，
  请保持同样语义，界面按 4 位验证码设计）；
- 违反上述约束不会让主流程崩溃：调用方走 `safe_available()` / `safe_classify()`，
  异常会被收敛成「不可用 / 空串」并回退到手动输入（但不是「可以不小心」的理由——
  异常路径会丢掉本次自动识别机会）。
