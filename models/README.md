# models/ —— 自研模型目录（内容不入库）

本目录存放**作者自行训练**的验证码识别模型，**不属于开源范围**，因此已加入
`.gitignore`（`models/*.onnx`）。仓库里只保留本说明文件。

## crnn.onnx（未包含在仓库中）

| 项 | 说明 |
| --- | --- |
| 用途 | 登录页算术验证码 `/ACaptcha.ashx`（200×60，如 `98加5`）的算式识别 |
| 结构 | CRNN（CNN + BiLSTM + CTC），输入 200×64 RGB 归一化到 [-1, 1]，输出 CTC 序列 |
| 字符集 | `0123456789加乘-÷`（14 类，blank 索引 0） |
| 体积 | 约 13.47 MB |
| 验证集准确率 | 91.4%（566/619） |
| 消费方 | `src/ocr_crnn.py`，运行时按 `models/crnn.onnx` 查找；打包后取 `sys._MEIPASS/models/` |

模型缺失时的行为：

- `src/ocr_crnn.py` 的 `available()` 返回 `False`；
- 上层按契约自动降级为「手动输入验证码」，不报错、不崩溃、不影响注销流程
  （注销页 `/CheckCode` 用的是 `ddddocr`，与本模型无关）。

## 自己放一份模型进来

- 路径固定为 `models/crnn.onnx`；
- 或用环境变量 `GUIT_CRNN_MODEL` 指向任意路径（便于 A/B 换模型，不改代码）；
- 自行训练的模型只要满足上面的输入尺寸、归一化方式与字符集顺序，即可直接替换。

## 本地构建与公开构建的差别

| 场景 | `models/crnn.onnx` | 构建结果 |
| --- | --- | --- |
| 本地（含模型） | 存在 | `--add-data models;models` 生效；`check_bundle.py` 把模型列为 **required**，漏打即构建失败 |
| 公开 CI / 克隆仓库 | 不存在 | 跳过 `--add-data`；`check_bundle.py` 把该断言降为 **notice**，构建照常通过 |

公开构建产物因此只带注销页的 `ddddocr` 自动识别，登录验证码需要手动输入答案。
