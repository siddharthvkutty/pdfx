import shutil
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader
from reportlab.pdfgen import canvas

import pdfx
from pdfx.gui import tools
from pdfx.gui.widgets import Grid, run_async

from test_core import labels, make_pdf


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def wait(cond, timeout=10):
    end = time.time() + timeout
    while not cond():
        assert time.time() < end, "timed out"
        QCoreApplication.processEvents()
        time.sleep(0.01)


@pytest.fixture
def pdf(tmp_path):
    return make_pdf(tmp_path / "a.pdf", "A", 5)


def test_ranges():
    assert tools.ranges([0, 1, 2, 4]) == "1-3,5"
    assert tools.ranges([3]) == "4"
    assert tools.ranges([]) == ""


def test_move_selected(qapp):
    g = Grid(editable=True)
    for i in range(6):
        g.add(str(i), i)

    def move(rows, target):
        g.clearSelection()
        for r in rows:
            g.item(r).setSelected(True)
        g.move_selected(target)
        return g.values()

    assert move([0], 3) == [1, 2, 0, 3, 4, 5]  # forward: lands before old item 3
    assert move([5], 0) == [5, 1, 2, 0, 3, 4]  # to the front
    assert move([1, 3], 6) == [5, 2, 3, 4, 1, 0]  # to the end, order among selected kept


def test_remove_selected(qapp):
    g = Grid(editable=True)
    for i in range(4):
        g.add(str(i), i)
    g.item(1).setSelected(True)
    g.item(2).setSelected(True)
    g.remove_selected()
    assert g.values() == [0, 3]


def test_run_async_calls_back_on_gui_thread(qapp):
    got = {}
    run_async(lambda: threading.get_ident(), lambda r: got.update(worker=r, cb=threading.get_ident()))
    run_async(lambda: 1 / 0, None, lambda m: got.update(err=m))
    wait(lambda: {"worker", "err"} <= got.keys())
    assert got["cb"] == threading.get_ident() != got["worker"]
    assert "division" in got["err"]


def test_thumbnails_arrive(qapp, pdf):
    g = Grid()
    g.load_pages(pdf, 5)
    blank = g.item(0).icon().pixmap(g.iconSize()).toImage()
    wait(lambda: all(g.item(i).icon().pixmap(g.iconSize()).toImage() != blank for i in range(5)))


def test_organize_end_to_end(qapp, pdf, tmp_path, monkeypatch):
    out = tmp_path / "out.pdf"
    t = tools.OrganizeTool()
    assert not t.button.isEnabled()
    t.add_files([str(pdf)])
    assert t.button.isEnabled() and t.grid.count() == 5
    t.grid.clearSelection()
    t.grid.item(4).setSelected(True)
    t.grid.move_selected(0)  # page 5 to front
    t.grid.clearSelection()
    t.grid.item(1).setSelected(True)  # original page 1, now second
    t.grid.remove_selected()
    done = []
    monkeypatch.setattr(t, "ask_save", lambda name: str(out))
    monkeypatch.setattr(t, "saved", lambda p, note="": done.append(p))
    t.go()
    wait(lambda: done)
    assert labels(out) == ["A5", "A2", "A3", "A4"]


def test_split_selection_and_text(qapp, pdf, tmp_path, monkeypatch):
    out = tmp_path / "out.pdf"
    t = tools.SplitTool()
    t.add_files([str(pdf)])
    for r in (1, 2, 4):
        t.grid.item(r).setSelected(True)
    assert t.pages.text() == "2-3,5"
    t.pages.setText("1,4")
    t.select_typed()
    assert sorted(t.grid.row(i) for i in t.grid.selectedItems()) == [0, 3]
    done = []
    monkeypatch.setattr(t, "ask_save", lambda name: str(out))
    monkeypatch.setattr(t, "saved", lambda p, note="": done.append(p))
    t.go()
    wait(lambda: done)
    assert labels(out) == ["A1", "A4"]


def test_merge_needs_two(qapp, pdf, tmp_path):
    t = tools.MergeTool()
    t.add_files([str(pdf)])
    assert not t.button.isEnabled()
    t.add_files([str(make_pdf(tmp_path / "b.pdf", "B", 2))])
    assert t.button.isEnabled()


def test_ppt_rejects_other_files(qapp, pdf, monkeypatch):
    warned = []
    monkeypatch.setattr(tools.QMessageBox, "warning", lambda *a: warned.append(a[2]))
    t = tools.PptTool()
    t.add_files([str(pdf)])
    assert warned and t.grid.count() == 0


from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


@pytest.fixture
def shown(qapp):
    g = Grid(editable=True)
    for i in range(8):
        g.add(str(i), i)
    g.resize(900, 600)
    g.show()
    wait(lambda: g.visualItemRect(g.item(7)).isValid() and g.visualItemRect(g.item(7)).width() > 0)
    yield g
    g.close()


def center(g, i):
    return g.visualItemRect(g.item(i)).center()


def drag(g, src, dst_point):
    vp = g.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(g, src))
    for step in (30, 60, 90):  # several moves, like a real mouse
        a = center(g, src)
        p = QPoint(a.x() + (dst_point.x() - a.x()) * step // 90, a.y() + (dst_point.y() - a.y()) * step // 90)
        QTest.mouseMove(vp, p)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, dst_point)


def test_mouse_drag_reorders(shown):
    g = shown
    drag(g, 0, center(g, 3) + QPoint(20, 0))  # right half of item 3 = after it
    assert g.values() == [1, 2, 3, 0, 4, 5, 6, 7]
    assert not g._dragging and g._drop is None


def test_mouse_drag_to_front_and_end(shown):
    g = shown
    drag(g, 5, center(g, 0) - QPoint(30, 0))
    assert g.values() == [5, 0, 1, 2, 3, 4, 6, 7]
    drag(g, 0, center(g, 7) + QPoint(30, 0))
    assert g.values() == [0, 1, 2, 3, 4, 6, 7, 5]


def test_mouse_drag_moves_whole_selection(shown):
    g = shown
    g.item(1).setSelected(True)
    g.item(2).setSelected(True)
    drag(g, 1, center(g, 6) + QPoint(20, 0))
    assert g.values() == [0, 3, 4, 5, 6, 1, 2, 7]


def test_click_without_drag_just_selects(shown):
    g = shown
    QTest.mouseClick(g.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(g, 2))
    assert g.values() == list(range(8)) and [g.row(i) for i in g.selectedItems()] == [2]


def test_keyboard_pick_up_and_move(shown):
    g = shown
    g.setCurrentRow(1)
    key = lambda k: QTest.keyClick(g, k)
    key(Qt.Key.Key_Return)  # pick up item 1
    key(Qt.Key.Key_Right)
    key(Qt.Key.Key_Right)
    assert g.values() == [0, 2, 3, 1, 4, 5, 6, 7]
    key(Qt.Key.Key_Left)
    key(Qt.Key.Key_Home)
    assert g.values()[0] == 1
    key(Qt.Key.Key_End)
    assert g.values()[-1] == 1
    key(Qt.Key.Key_Return)  # put down: arrows navigate again instead of moving
    key(Qt.Key.Key_Left)
    assert g.values()[-1] == 1
    assert g._grab is None


def test_keyboard_escape_drops_and_vertical_moves(shown):
    g = shown
    cols = g.viewport().width() // g.gridSize().width()
    assert cols < 8, "need a wrapped grid for this test"
    g.setCurrentRow(0)
    QTest.keyClick(g, Qt.Key.Key_Return)
    QTest.keyClick(g, Qt.Key.Key_Down)
    assert g.values().index(0) == cols
    QTest.keyClick(g, Qt.Key.Key_Escape)
    assert g._grab is None


def test_reset_clears_tool(qapp, pdf):
    t = tools.OrganizeTool()
    t.add_files([str(pdf)])
    assert t.grid.count() == 5
    t.reset_btn.click()
    assert t.grid.count() == 0 and t.src is None and not t.button.isEnabled() and t.canvas.currentIndex() == 0


@pytest.mark.parametrize("editable", [False, True])
def test_pdf_to_ppt_tool_end_to_end(qapp, pdf, tmp_path, monkeypatch, editable):
    from pptx import Presentation

    if editable and not shutil.which("soffice"):
        pytest.skip("LibreOffice not installed")
    out = tmp_path / "o.pptx"
    t = tools.PdfToPptTool()
    t.add_files([str(pdf)])
    t.group.button(0 if editable else 1).setChecked(True)
    done = []
    monkeypatch.setattr(t, "ask_save", lambda name, filt=None: str(out))
    monkeypatch.setattr(t, "saved", lambda p, note="": done.append(p))
    t.go()
    wait(lambda: done, timeout=60)
    assert len(Presentation(out).slides) == 5


def test_conversion_and_thumbnails_share_pdfium_safely(qapp, pdf, tmp_path):
    """Thumbnails render while a conversion runs: both must go through the pdfium lock without crashing."""
    g = Grid()
    g.load_pages(pdf, 5)
    done = []
    run_async(lambda: pdfx.pdf_to_ppt(pdf, tmp_path / "o.pptx", editable=False), done.append)
    wait(lambda: done)
    assert done[0] == tmp_path / "o.pptx"


def test_window_branding(qapp):
    from PySide6.QtGui import QPixmap

    from pdfx.gui.app import Window
    from pdfx.gui.theme import ICON

    assert not QPixmap(str(ICON)).isNull(), "icon missing or unreadable"
    assert Window().windowTitle() == "pdfX"


def test_no_libreoffice_greys_out_and_offers_download(qapp, monkeypatch):
    import pdfx.gui.app as appmod

    monkeypatch.setattr(pdfx, "libreoffice_path", lambda: None)
    asked = []
    monkeypatch.setattr(appmod, "ask_install_libreoffice", lambda parent: asked.append(1))
    w = appmod.Window()
    ppt_tool, ppt_card = next(c for c in w.cards if c[0].needs_libreoffice)
    other_card = next(c for t, c in w.cards if not t.needs_libreoffice)
    assert ppt_card.graphicsEffect() is not None and other_card.graphicsEffect() is None
    assert "LibreOffice" in ppt_card.blurb_label.text()
    QTest.mouseClick(ppt_card, Qt.MouseButton.LeftButton)
    assert asked == [1] and w.stack.currentWidget() is w.home  # explained, did not open the tool

    # once installed, the same click opens the tool and the tile is back to normal
    monkeypatch.setattr(pdfx, "libreoffice_path", lambda: "/usr/bin/soffice")
    QTest.mouseClick(ppt_card, Qt.MouseButton.LeftButton)
    assert w.stack.currentWidget() is ppt_tool and asked == [1]
    w.show_tool(w.home)
    assert ppt_card.graphicsEffect() is None


def test_pdf_to_ppt_editable_needs_libreoffice(qapp, pdf, monkeypatch):
    asked = []
    monkeypatch.setattr(tools, "ask_install_libreoffice", lambda parent: asked.append(1))
    monkeypatch.setattr(pdfx, "libreoffice_path", lambda: None)
    t = tools.PdfToPptTool()
    t.on_show()
    editable, exact = t.group.button(0), t.group.button(1)
    assert exact.isChecked() and "needs LibreOffice" in editable.text()  # falls back to what works
    editable.click()
    assert asked == [1] and exact.isChecked()  # click explains, selection reverts

    monkeypatch.setattr(pdfx, "libreoffice_path", lambda: "/usr/bin/soffice")
    editable.click()
    assert asked == [1] and editable.isChecked() and editable.text() == "Editable (text stays text)"


def test_libreoffice_path_none_when_missing(monkeypatch):
    import pdfx.core as core

    monkeypatch.setattr(core.shutil, "which", lambda name: None)
    monkeypatch.setattr(core.sys, "platform", "linux")
    assert core.libreoffice_path() is None


def _img(path, size, color="red", mode="RGB"):
    from PIL import Image

    Image.new(mode, size, color).save(path)
    return str(path)


def test_images_to_pdf_tool_end_to_end(qapp, tmp_path, monkeypatch):
    out = tmp_path / "o.pdf"
    wide = _img(tmp_path / "wide.jpg", (300, 100))
    tall = _img(tmp_path / "tall.png", (100, 300), mode="RGBA", color=(0, 0, 255, 128))
    sq = _img(tmp_path / "sq.webp", (200, 200))
    t = tools.ImagesToPdfTool()
    assert not t.button.isEnabled()
    t.add_files([wide, tall, sq])
    assert t.button.isEnabled() and t.grid.count() == 3

    blank = t.grid.item(0).icon().pixmap(t.grid.iconSize()).toImage()
    wait(lambda: all(t.grid.item(i).icon().pixmap(t.grid.iconSize()).toImage() != blank for i in range(3)))

    t.grid.clearSelection()
    t.grid.item(2).setSelected(True)
    t.grid.move_selected(0)  # square image to the front
    done = []
    monkeypatch.setattr(t, "ask_save", lambda name, filt=None: str(out))
    monkeypatch.setattr(t, "saved", lambda p, note="": done.append(p))
    t.go()
    wait(lambda: done)
    sizes = [(round(p.mediabox.width), round(p.mediabox.height)) for p in PdfReader(out).pages]
    assert sizes == [(96, 96), (144, 48), (48, 144)]  # sq, wide, tall at the assumed 150 dpi


def test_images_to_pdf_tool_rejects_non_images_but_keeps_the_rest(qapp, pdf, tmp_path, monkeypatch):
    warned = []
    monkeypatch.setattr(tools.QMessageBox, "warning", lambda *a: warned.append(a[2]))
    t = tools.ImagesToPdfTool()
    t.add_files([_img(tmp_path / "ok.png", (10, 10)), str(pdf)])
    assert t.grid.count() == 1 and warned and "a.pdf" in warned[0]


def test_home_has_the_image_tool(qapp):
    from pdfx.gui.app import Window

    assert any(isinstance(tool, tools.ImagesToPdfTool) for tool, _ in Window().cards)
