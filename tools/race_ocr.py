"""证明 ocr_helper.OcrEngine.available() 的并发竞态：
两个线程同时首次调用时，先到的线程把 _initialized 置 True 但还没建好引擎，
后到的线程会看到 _engine is None -> 误判"OCR 不可用"（GUI 上表现为"要求手输验证码"）。
"""
import os
import sys
import threading
import time
import types

TARGET = sys.argv[1]
sys.path.insert(0, TARGET)

# 用"慢导入"的假 ddddocr 放大竞态窗口
fake = types.ModuleType('ddddocr')


class _Ocr:
    def __init__(self, show_ad=False):
        time.sleep(0.5)


fake.DdddOcr = _Ocr
sys.modules['ddddocr'] = fake

import ocr_helper  # noqa: E402

engine = ocr_helper.OcrEngine()
results = []
barrier = threading.Barrier(2)


def worker():
    barrier.wait()
    results.append(engine.available())


threads = [threading.Thread(target=worker) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print('RACE %s results=%s  -> %s' % (TARGET, sorted(results),
                                     'OK(都可用)' if all(results) else 'RACE(有线程误判不可用)'))
