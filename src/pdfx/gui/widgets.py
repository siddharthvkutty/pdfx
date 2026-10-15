"""Qt building blocks: background jobs and a thumbnail grid with drag-to-reorder."""
from __future__ import annotations

import pypdfium2 as pdfium
from PySide6.QtCore import QItemSelectionModel, QObject, QPoint, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QAbstractItemView, QApplication, QFrame, QListView, QListWidget, QListWidgetItem

from pdfx.core import pdfium_lock

from .theme import PAPER, PAPER_EDGE, PAPER_SHADE, RED

THUMB = QSize(150, 200)


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, QImage)


class _Job(QRunnable):
    def __init__(self, fn, wants_progress):
        super().__init__()
        self.setAutoDelete(False)  # the Python side owns it, see _live
        self.fn, self.wants_progress, self.signals = fn, wants_progress, _Signals()

    def run(self):
        try:
            out = self.fn(self.signals.progress.emit) if self.wants_progress else self.fn()
        except Exception as e:
            self.signals.failed.emit(str(e))
        else:
            self.signals.done.emit(out)


_live: set[_Job] = set()  # keeps jobs and their signal objects alive until results are delivered
# pdfium is not thread-safe: all rendering goes through one thread.
_render_pool = QThreadPool()
_render_pool.setMaxThreadCount(1)


def thumb_icon(pm: QPixmap) -> QIcon:
    """Same picture in every state; Qt would otherwise tint the selected one with the system highlight colour."""
    icon = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
        icon.addPixmap(pm, mode)
    return icon


def run_async(fn, done=None, failed=None, *, progress=None, pool=None) -> None:
    """Run fn() on a worker thread; done(result) / failed(message) are called on the GUI thread."""
    job = _Job(fn, progress is not None)
    _live.add(job)

    def finish(cb, arg):
        _live.discard(job)
        if cb:
            cb(arg)

    job.signals.done.connect(lambda r: finish(done, r))
    job.signals.failed.connect(lambda m: finish(failed, m))
    if progress:
        job.signals.progress.connect(progress)
    (pool or QThreadPool.globalInstance()).start(job)


class Grid(QListWidget):
    """Icon grid. With editable=True items can be reordered and removed.

    Reorder by mouse (press, drag, release; handled here, not by Qt's native drag-and-drop, which
    depends on the platform) or by keyboard (Enter picks up the current item, arrows move it,
    Enter or Esc puts it down).
    """

    filesDropped = Signal(list)  # files dragged in from the file manager
    changed = Signal()

    def __init__(self, editable=False, selectable=True):
        super().__init__()
        self.editable = editable
        self._gen = 0  # bumped by clear() so stale thumbnail jobs stop early
        self._moving = False
        self._press: tuple[QPoint, QListWidgetItem] | None = None  # where a possible drag started
        self._dragging = False
        self._pos = QPoint()
        self._drop: int | None = None  # insertion row while dragging
        self._grab: QListWidgetItem | None = None  # item picked up with Enter
        self._scroll = QTimer(self)
        self._scroll.setInterval(30)
        self._scroll.timeout.connect(self._autoscroll)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setIconSize(THUMB)
        self.setGridSize(QSize(THUMB.width() + 36, THUMB.height() + 56))
        self.setWordWrap(True)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection if selectable else QAbstractItemView.SelectionMode.NoSelection
        )
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)  # file-manager drops only
        for sig in (self.model().rowsInserted, self.model().rowsRemoved):
            sig.connect(self._emit_changed)

    def _emit_changed(self, *_):
        if not self._moving:
            self.changed.emit()

    # -- content ---------------------------------------------------------
    def add(self, text, data, icon=None) -> QListWidgetItem:
        if icon is None:
            pm = QPixmap(THUMB)
            pm.fill(Qt.GlobalColor.white)
            icon = thumb_icon(pm)
        item = QListWidgetItem(icon, text)
        item.setData(Qt.ItemDataRole.UserRole, data)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.addItem(item)
        if self.count() == 1:  # so Enter has an item to pick up before any click
            self.setCurrentRow(0, QItemSelectionModel.SelectionFlag.NoUpdate)
        return item

    def values(self) -> list:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def clear(self):
        self._gen += 1
        self._grab = None
        super().clear()

    def load_pages(self, path, count):
        """One item per page; data is (path, 0-based page index)."""
        self.clear()
        self.render([self.add(str(i + 1), (str(path), i)) for i in range(count)], path, list(range(count)))

    def render(self, items, path, pages):
        """Fill items' icons with thumbnails of `pages` of `path`, in the background."""
        gen, width = self._gen, int(THUMB.width() * self.devicePixelRatioF())

        def work(emit):
            with pdfium_lock:
                pdf = pdfium.PdfDocument(str(path))
            try:
                for k, p in enumerate(pages):
                    if gen != self._gen:
                        return
                    with pdfium_lock:  # per page, so a conversion running at the same time can interleave
                        page = pdf[p]
                        bm = page.render(scale=width / page.get_width())
                        img = QImage(bm.buffer, bm.width, bm.height, bm.stride, QImage.Format.Format_BGR888).copy()
                    emit(k, img)
            finally:
                with pdfium_lock:
                    pdf.close()

        def show(k, img):
            try:
                items[k].setIcon(thumb_icon(QPixmap.fromImage(img)))
            except RuntimeError:  # item was removed meanwhile
                pass

        run_async(work, progress=show, pool=_render_pool)

    # -- editing ---------------------------------------------------------
    def remove_selected(self):
        for item in self.selectedItems():
            self.takeItem(self.row(item))

    def move_selected(self, row):
        """Move the selected items so they start at `row` (a position in the pre-move list)."""
        rows = sorted(self.row(i) for i in self.selectedItems())
        row -= sum(r < row for r in rows)
        self._moving = True
        try:
            items = [self.takeItem(r) for r in reversed(rows)][::-1]
            for k, item in enumerate(items):
                self.insertItem(row + k, item)
                item.setSelected(True)
        finally:
            self._moving = False
        self.changed.emit()

    def _relocate(self, item, new_row):
        new_row = max(0, min(self.count() - 1, new_row))
        if new_row == self.row(item):
            return
        self._moving = True
        try:
            self.insertItem(new_row, self.takeItem(self.row(item)))
        finally:
            self._moving = False
        self.setCurrentItem(item)
        item.setSelected(True)
        self.scrollToItem(item)
        self.changed.emit()

    # -- keyboard --------------------------------------------------------
    def keyPressEvent(self, e):
        key = e.key()
        if self.editable:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._grab:
                    self._grab = None
                elif item := self.currentItem():
                    self._grab = item
                    self.clearSelection()
                    item.setSelected(True)
                self.viewport().update()
                return
            if self._grab:
                if key == Qt.Key.Key_Escape:
                    self._grab = None
                    self.viewport().update()
                    return
                cols = max(1, self.viewport().width() // self.gridSize().width())
                step = {
                    Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -cols, Qt.Key.Key_Down: cols,
                }.get(key)
                if key == Qt.Key.Key_Home:
                    self._relocate(self._grab, 0)
                elif key == Qt.Key.Key_End:
                    self._relocate(self._grab, self.count() - 1)
                elif step:
                    self._relocate(self._grab, self.row(self._grab) + step)
                if step or key in (Qt.Key.Key_Home, Qt.Key.Key_End):
                    self.viewport().update()
                    return
            elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self.remove_selected()
                return
        super().keyPressEvent(e)

    # -- mouse reorder ---------------------------------------------------
    def _row_at(self, pos) -> int:
        for i in range(self.count()):
            r = self.visualItemRect(self.item(i))
            if pos.y() < r.top() or (pos.y() <= r.bottom() and pos.x() < r.center().x()):
                return i
        return self.count()

    def mousePressEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        self._press = (e.position().toPoint(), item) if self.editable and item and e.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not self._press:
            return super().mouseMoveEvent(e)
        self._pos = e.position().toPoint()
        if not self._dragging:
            if (self._pos - self._press[0]).manhattanLength() < QApplication.startDragDistance():
                return
            if not self._press[1].isSelected():
                return  # pressed with a modifier that deselected it
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._scroll.start()
        self._drop = self._row_at(self._pos)
        self.viewport().update()

    def mouseReleaseEvent(self, e):
        if not self._dragging:
            self._press = None
            return super().mouseReleaseEvent(e)
        self._finish_drag(move=True)

    def _finish_drag(self, move):
        if move and self._drop is not None:
            self.move_selected(self._drop)
        self._press, self._dragging, self._drop = None, False, None
        self._scroll.stop()
        self.unsetCursor()
        self.setState(QAbstractItemView.State.NoState)
        self.viewport().update()

    def _autoscroll(self):
        edge, bar = 40, self.verticalScrollBar()
        if self._pos.y() < edge:
            bar.setValue(bar.value() - 24)
        elif self._pos.y() > self.viewport().height() - edge:
            bar.setValue(bar.value() + 24)
        self._drop = self._row_at(self._pos)
        self.viewport().update()

    # -- drops from the file manager --------------------------------------
    def _urls(self, e):
        return [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]

    def dragEnterEvent(self, e):
        if self._urls(e):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        if files := self._urls(e):
            self.filesDropped.emit(files)
        e.acceptProposedAction()

    # -- painting --------------------------------------------------------
    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.count():
            return
        p = QPainter(self.viewport())
        accent = QColor(RED)
        if self._grab and self._grab.listWidget() is self:
            r = self.visualItemRect(self._grab)
            p.setPen(QPen(QColor(PAPER), 5))  # paper-white frame: distinct from the red selection
            p.drawRect(r.adjusted(2, 2, -2, -2))
        if self._dragging and self._drop is not None:
            last = self._drop >= self.count()
            r = self.visualItemRect(self.item(self.count() - 1 if last else self._drop))
            x = r.right() if last else r.left()
            p.setPen(QPen(accent, 4))
            p.drawLine(x, r.top() + 4, x, r.bottom() - 4)
            ghost = self._press[1].icon().pixmap(THUMB).scaledToWidth(80)
            p.setOpacity(0.75)
            p.drawPixmap(self._pos - QPoint(ghost.width() // 2, ghost.height() // 2), ghost)


class Sheet(QFrame):
    """A sheet of paper with a folded top-right corner, the shape of the app icon.

    With hoverable=True the fold turns red under the cursor.
    """

    def __init__(self, fold=34, radius=10, hoverable=False):
        super().__init__()
        self._fold, self._radius, self._hoverable, self._hover = fold, radius, hoverable, False

    def enterEvent(self, e):
        self._hover = self._hoverable
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        w, h, f, r = self.width(), self.height(), self._fold, self._radius
        path = QPainterPath()
        path.moveTo(r, 0)
        path.lineTo(w - f, 0)
        path.lineTo(w, f)
        path.lineTo(w, h - r)
        path.arcTo(w - 2 * r, h - 2 * r, 2 * r, 2 * r, 0, -90)
        path.lineTo(r, h)
        path.arcTo(0, h - 2 * r, 2 * r, 2 * r, 270, -90)
        path.lineTo(0, r)
        path.arcTo(0, 0, 2 * r, 2 * r, 180, -90)
        path.closeSubpath()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff" if self._hover else PAPER))
        p.drawPath(path)
        p.setBrush(QColor(RED if self._hover else PAPER_SHADE))
        p.drawPolygon(QPolygonF([QPointF(w - f, 0), QPointF(w - f, f), QPointF(w, f)]))
        self.paint_content(p, w, h)

    def paint_content(self, p, w, h):
        """Hook for subclasses to draw on the sheet."""
