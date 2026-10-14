"""界面布局验收（主线独立用例）：窗口映射后必须等于控件请求尺寸，且没有任何控件越界。

说明（重要）：早期用非 DPI 感知的截图工具抓到"窗口 329x583、右侧被裁"，那是截图进程
被 Windows DPI 虚拟化造成的**采集伪影**，不是程序缺陷：在 DPI 感知条件下，原始程序
（exe 与源码态一致）窗口 = 请求尺寸（150% 缩放下 494x874），全部控件完整可见。
因此本用例的判据是"映射窗口 >= 请求尺寸 且 无控件越界"，作为真实回归护栏。
"""
import io
import json
import tempfile
import time

import PIL.Image

import support


def _boot(mapped=True):
    sb = support.Sandbox(tempfile.mkdtemp(prefix='guit-layout-'))
    sb.install()
    import tkinter as tk
    import app as appmod
    support.patch_app_sandbox(appmod, sb.tmp)
    portal = support.MockPortal()
    cfg = portal.config()
    appmod.load_config = lambda: json.loads(json.dumps(cfg))
    root = tk.Tk()
    if mapped:
        root.geometry('+40+40')
    else:
        root.withdraw()
    root.update()
    ui = appmod.LoginApp(root)
    settle(root, ui)
    return sb, portal, appmod, root, ui


def settle(root, ui, rounds=8):
    for _ in range(rounds):
        root.update()
        time.sleep(0.02)


def _descendants(widget):
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out.extend(_descendants(child))
    return out


def _overflow(root, widget):
    rx, ry = root.winfo_rootx(), root.winfo_rooty()
    wx, wy = widget.winfo_rootx(), widget.winfo_rooty()
    over_w = (wx - rx) + widget.winfo_width() - root.winfo_width()
    over_h = (wy - ry) + widget.winfo_height() - root.winfo_height()
    return over_w, over_h


def _assert_no_clipping(root, label):
    bad = []
    for w in _descendants(root):
        if not w.winfo_ismapped():
            continue
        ow, oh = _overflow(root, w)
        if ow > 2 or oh > 2:
            bad.append((w.winfo_class(), str(w), ow, oh))
    assert not bad, f'{label}: 以下控件超出窗口被裁切 (class, widget, 越界宽, 越界高): ' + repr(bad[:8])


def test_window_fits_all_widgets():
    sb, portal, appmod, root, ui = _boot()
    try:
        assert root.winfo_width() >= root.winfo_reqwidth(), (
            f'窗口宽度 {root.winfo_width()} 小于控件请求宽度 {root.winfo_reqwidth()}')
        assert root.winfo_height() >= root.winfo_reqheight(), (
            f'窗口高度 {root.winfo_height()} 小于控件请求高度 {root.winfo_reqheight()}')
        _assert_no_clipping(root, '初始布局')
    finally:
        portal.stop()
        root.destroy()


def test_window_fits_after_captcha_image():
    """验证码按像素放大显示（80x24 -> 4x）后，窗口仍必须完整容纳它，不得裁切。"""
    sb, portal, appmod, root, ui = _boot()
    try:
        buf = io.BytesIO()
        PIL.Image.new('RGB', (80, 24), (255, 255, 255)).save(buf, 'PNG')
        ui._show_captcha(buf.getvalue())
        settle(root, ui)
        assert ui.photo is not None, '验证码图像必须被渲染'
        assert ui.photo.width() == 80 * appmod.CAPTCHA_ZOOM, ui.photo.width()
        ow, oh = _overflow(root, ui.lbl_captcha)
        assert ow <= 2 and oh <= 2, f'验证码区域被裁切（越界 {ow}x{oh}），图片宽 {ui.photo.width()}'
        for w in (ui.btn_connect, ui.txt_log):
            ow, oh = _overflow(root, w)
            assert ow <= 2 and oh <= 2, f'{w} 被裁切（越界 {ow}x{oh}）'
        _assert_no_clipping(root, '验证码显示后')
    finally:
        portal.stop()
        root.destroy()


def test_window_height_can_fit_small_screens():
    """窗口高度必须能放进屏幕可用区（高 DPI 小屏下不把免责声明挤出屏幕外）。"""
    sb, portal, appmod, root, ui = _boot()
    try:
        avail_h = root.winfo_screenheight()
        assert root.winfo_height() <= avail_h, (
            f'窗口高度 {root.winfo_height()} 超过屏幕高度 {avail_h}（高 DPI 小屏会挤出屏幕）')
    finally:
        portal.stop()
        root.destroy()
