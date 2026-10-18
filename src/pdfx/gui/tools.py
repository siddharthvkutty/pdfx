"""One page per tool. Each is a canvas (left) plus an options panel with the action button (right)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QStackedWidget, QStyle, QTabWidget, QVBoxLayout, QWidget,
)

import pdfx

from .widgets import Grid, Sheet, run_async

PDF = "PDF files (*.pdf)"
LIBREOFFICE_URL = "https://www.libreoffice.org/download/download-libreoffice/"


def ask_install_libreoffice(parent):
    box = QMessageBox(parent)
    box.setWindowTitle("LibreOffice needed")
    box.setText("This feature needs LibreOffice.")
    box.setInformativeText(
        "pdfX uses the free LibreOffice to read presentations. Install it, then come back. pdfX finds it automatically."
    )
    get = box.addButton("Download LibreOffice", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is get:
        QDesktopServices.openUrl(QUrl(LIBREOFFICE_URL))


def ranges(rows: list[int]) -> str:
    """[0, 1, 2, 4] -> '1-3,5' (rows are 0-based, text is 1-based)."""
    spans: list[list[int]] = []
    for r in rows:
        if spans and r == spans[-1][1] + 1:
            spans[-1][1] = r
        else:
            spans.append([r, r])
    return ",".join(str(a + 1) if a == b else f"{a + 1}-{b + 1}" for a, b in spans)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class Tool(QWidget):
    title = blurb = action = ""
    needs_libreoffice = False  # the home screen greys the tool out until LibreOffice is found
    drop = "Drop a PDF here"
    exts = PDF
    multi = False
    editable = False  # grid items can be reordered / removed
    selectable = True

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.src: Path | None = None

        self.grid = Grid(self.editable, self.selectable)
        self.grid.filesDropped.connect(self.add_files)
        self.grid.changed.connect(self.refresh)

        pick = QPushButton("Select files" if self.multi else "Select file")
        pick.setObjectName("primary")
        pick.setFixedWidth(260)
        pick.clicked.connect(self.pick)
        big = QLabel(self.drop)
        big.setObjectName("dropTitle")
        field = Sheet(fold=52, radius=14)
        fl = QVBoxLayout(field)
        fl.addStretch()
        fl.addWidget(big, alignment=Qt.AlignmentFlag.AlignCenter)
        fl.addSpacing(18)
        fl.addWidget(pick, alignment=Qt.AlignmentFlag.AlignCenter)
        fl.addStretch()
        prompt = QWidget()
        pl = QVBoxLayout(prompt)
        pl.setContentsMargins(36, 36, 36, 36)
        pl.addWidget(field)

        self.canvas = QStackedWidget()
        self.canvas.addWidget(prompt)
        self.canvas.addWidget(self.grid)

        self.panel = QFrame()
        self.panel.setObjectName("panel")
        self.panel.setFixedWidth(320)
        col = QVBoxLayout(self.panel)
        head = QLabel(self.title)
        head.setObjectName("panelTitle")
        head.setWordWrap(True)
        self.reset_btn = QPushButton("× Reset")
        self.reset_btn.setObjectName("reset")
        self.reset_btn.setToolTip("Remove all files and start over")
        self.reset_btn.clicked.connect(self.reset)
        top = QHBoxLayout()
        top.addWidget(head)
        top.addStretch()
        top.addWidget(self.reset_btn)
        col.addLayout(top)
        self.info = QLabel()
        self.info.setWordWrap(True)
        col.addWidget(self.info)
        self.build_options(col)
        self.default_info = self.info.text()
        col.addStretch()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        col.addWidget(self.progress)
        self.button = QPushButton(self.action)
        self.button.setObjectName("primary")
        self.button.clicked.connect(self.go)
        col.addWidget(self.button)
        self.gated = [self.button]  # widgets enabled only when ready()

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.canvas, 1)
        row.addWidget(self.panel)
        self.refresh()

    # -- hooks for subclasses ---------------------------------------------
    def build_options(self, layout): ...

    def on_show(self): ...

    def load(self, paths: list[str]): raise NotImplementedError

    def go(self): raise NotImplementedError

    def ready(self) -> bool:
        return self.grid.count() > 0

    # -- shared plumbing --------------------------------------------------
    def showEvent(self, e):
        self.on_show()
        super().showEvent(e)

    def reset(self):
        self.grid.clear()
        self.src = None
        self.info.setText(self.default_info)
        self.refresh()

    def refresh(self):
        self.canvas.setCurrentIndex(1 if self.grid.count() else 0)
        self.reset_btn.setEnabled(self.grid.count() > 0)
        for w in self.gated:
            w.setEnabled(self.ready())

    def pick(self):
        if self.multi:
            paths, _ = QFileDialog.getOpenFileNames(self, "Select files", "", self.exts)
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Select file", "", self.exts)
            paths = [p] if p else []
        if paths:
            self.add_files(paths)

    def add_files(self, paths):
        try:
            self.load(paths)
        except pdfx.PdfxError as e:
            QMessageBox.warning(self, "pdfX", str(e))
        self.refresh()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def run(self, fn, done):
        def finish(cb, arg):
            self.panel.setEnabled(True)
            self.progress.hide()
            cb(arg)

        self.panel.setEnabled(False)
        self.progress.show()
        run_async(fn, lambda r: finish(done, r), lambda m: finish(lambda m: QMessageBox.warning(self, "pdfX", m), m))

    def ask_save(self, name: str, filt: str = PDF) -> str | None:
        start = str((self.src.parent if self.src else Path.home()) / name)
        p, _ = QFileDialog.getSaveFileName(self, "Save as", start, filt)
        ext = Path(name).suffix
        return (p if p.lower().endswith(ext) else p + ext) if p else None

    def ask_folder(self) -> str | None:
        return QFileDialog.getExistingDirectory(self, "Choose output folder", str(self.src.parent if self.src else Path.home())) or None

    def saved(self, path, note=""):
        path = Path(path)
        box = QMessageBox(self)
        box.setWindowTitle("Done")
        box.setText(f"Saved {path.name}" if path.is_file() else "Done")
        box.setInformativeText("\n".join(filter(None, [note, str(path)])))
        open_btn = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.is_dir() else path.parent)))


class PageTool(Tool):
    """Base for tools that work on one PDF and show its pages."""

    def load(self, paths):
        path = paths[0]
        n = pdfx.page_count(path)  # raises PdfxError for unreadable/encrypted files
        self.src = Path(path)
        self.grid.load_pages(path, n)
        self.info.setText(f"{self.src.name} · {n} pages · {human_size(self.src.stat().st_size)}")


class MergeTool(Tool):
    title, blurb, action = "Merge PDF", "Combine PDFs in the order you want.", "Merge PDF"
    multi, editable = True, True
    drop = "Drop PDFs here"

    def build_options(self, layout):
        self.info.setText("Add at least two PDFs. Drag them to set the order, or press Enter on one and use the arrow keys (Enter again to drop). Delete removes the selected file.")

    def ready(self):
        return self.grid.count() >= 2

    def load(self, paths):
        bad = []
        for p in paths:
            try:
                n = pdfx.page_count(p)
            except pdfx.PdfxError as e:
                bad.append(str(e))
                continue
            self.src = self.src or Path(p)
            name = Path(p).name
            item = self.grid.add(f"{name if len(name) <= 22 else name[:19] + '…'}\n{n} pages", str(p))
            self.grid.render([item], p, [0])
        if bad:
            raise pdfx.PdfxError("\n".join(bad))

    def go(self):
        files = self.grid.values()
        if out := self.ask_save("merged.pdf"):
            self.run(lambda: pdfx.merge(files, out), self.saved)


class OrganizeTool(PageTool):
    title, blurb, action = "Organize pages", "Reorder or delete pages.", "Save PDF"
    editable = True

    def build_options(self, layout):
        self.info.setText("Drag pages to reorder them, or press Enter on a page and use the arrow keys (Enter again to drop). Select pages and press Delete to remove them.")

    def go(self):
        order = [i for _, i in self.grid.values()]
        if out := self.ask_save(f"{self.src.stem}_organized.pdf"):
            self.run(lambda: pdfx.reorder(self.src, order, out), self.saved)


class SplitTool(PageTool):
    title, blurb, action = "Split / Extract", "Pull out a page or a range, or split into single pages.", "Extract pages"

    def build_options(self, layout):
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("e.g. 3 or 2-5 or 1,4,7-9")
        self.pages.editingFinished.connect(self.select_typed)
        layout.addWidget(QLabel("Pages to extract"))
        layout.addWidget(self.pages)
        self.grid.itemSelectionChanged.connect(self.fill_text)
        self.split_all = QPushButton("Split into single pages")
        layout.addWidget(self.split_all)
        self.split_all.clicked.connect(self.split_pages)

    def refresh(self):
        super().refresh()
        if hasattr(self, "split_all"):
            self.split_all.setEnabled(self.ready())

    def reset(self):
        self.pages.clear()
        super().reset()

    def fill_text(self):
        if rows := sorted(self.grid.row(i) for i in self.grid.selectedItems()):
            self.pages.setText(ranges(rows))

    def select_typed(self):
        try:
            rows = pdfx.parse_pages(self.pages.text(), self.grid.count())
        except pdfx.PdfxError:
            return  # reported when the user presses the button
        self.grid.blockSignals(True)
        self.grid.clearSelection()
        for r in rows:
            self.grid.item(r).setSelected(True)
        self.grid.blockSignals(False)

    def go(self):
        spec = self.pages.text()
        try:
            pdfx.parse_pages(spec, self.grid.count())
        except pdfx.PdfxError as e:
            return QMessageBox.warning(self, "pdfX", str(e))
        if out := self.ask_save(f"{self.src.stem}_pages_{spec.replace(',', '_').replace(' ', '')}.pdf"):
            self.run(lambda: pdfx.extract(self.src, spec, out), self.saved)

    def split_pages(self):
        if folder := self.ask_folder():
            self.run(lambda: pdfx.split(self.src, folder), lambda _: self.saved(folder, "One file per page."))


class WatermarkTool(PageTool):
    title, blurb, action = "Watermark", "Stamp text or an image on every page.", "Add watermark"
    selectable = False

    def build_options(self, layout):
        self.image: str | None = None
        self.tabs = QTabWidget()
        t = QWidget()
        t.setObjectName("tabpage")
        tf = QFormLayout(t)
        self.text = QLineEdit("CONFIDENTIAL")
        self.size = QSpinBox()
        self.size.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.size.setRange(10, 300)
        self.size.setValue(60)
        tf.addRow("Text", self.text)
        tf.addRow("Font size", self.size)
        i = QWidget()
        i.setObjectName("tabpage")
        il = QFormLayout(i)
        choose = QPushButton("Choose image…")
        choose.clicked.connect(self.choose_image)
        self.image_name = QLabel("No image chosen")
        self.scale = QSpinBox()
        self.scale.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.scale.setRange(5, 100)
        self.scale.setValue(50)
        self.scale.setSuffix(" % of page width")
        il.addRow(choose)
        il.addRow(self.image_name)
        il.addRow("Size", self.scale)
        self.tabs.addTab(t, "Text")
        self.tabs.addTab(i, "Image")
        layout.addWidget(self.tabs)

        common = QFormLayout()
        self.opacity = QSpinBox()
        self.opacity.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(30)
        self.opacity.setSuffix(" %")
        self.angle = QSpinBox()
        self.angle.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.angle.setRange(-180, 180)
        self.angle.setValue(45)
        self.angle.setSuffix("°")
        common.addRow("Opacity", self.opacity)
        common.addRow("Rotation", self.angle)
        layout.addLayout(common)
        self.tabs.currentChanged.connect(lambda n: self.angle.setValue(45 if n == 0 else 0))

    def choose_image(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose image", "", "Images (*.png *.jpg *.jpeg)")
        if p:
            self.image = p
            self.image_name.setText(Path(p).name)

    def go(self):
        opacity, angle = self.opacity.value() / 100, self.angle.value()
        if self.tabs.currentIndex() == 0:
            text, size = self.text.text(), self.size.value()
            op = lambda out: pdfx.watermark_text(self.src, text, out, opacity=opacity, font_size=size, angle=angle)
        else:
            if not self.image:
                return QMessageBox.warning(self, "pdfX", "Choose an image first.")
            img, scale = self.image, self.scale.value() / 100
            op = lambda out: pdfx.watermark_image(self.src, img, out, opacity=opacity, scale=scale, angle=angle)
        if out := self.ask_save(f"{self.src.stem}_watermarked.pdf"):
            self.run(lambda: op(out), self.saved)


class CompressTool(PageTool):
    title, blurb, action = "Compress PDF", "Shrink file size with Ghostscript.", "Compress PDF"
    selectable = False
    LEVELS = [("Less compression (best quality)", "printer"), ("Recommended", "ebook"), ("Extreme compression", "screen")]

    def build_options(self, layout):
        self.group = QButtonGroup(self)
        for n, (label, level) in enumerate(self.LEVELS):
            b = QRadioButton(label)
            b.setProperty("level", level)
            b.setChecked(level == "ebook")
            self.group.addButton(b, n)
            layout.addWidget(b)

    def go(self):
        level = self.group.checkedButton().property("level")
        before = self.src.stat().st_size
        if out := self.ask_save(f"{self.src.stem}_compressed.pdf"):
            def done(p):
                after = Path(p).stat().st_size
                note = f"{human_size(before)} → {human_size(after)}" if after < before else "Could not reduce the size; saved the original."
                self.saved(p, note)

            self.run(lambda: pdfx.compress(self.src, out, level), done)


class PptTool(Tool):
    title, blurb, action = "PowerPoint to PDF", "Convert presentations with LibreOffice.", "Convert to PDF"
    multi, editable = True, True
    needs_libreoffice = True
    drop = "Drop presentations here"
    exts = "Presentations (*.ppt *.pptx *.pps *.ppsx *.odp)"
    SUFFIXES = {".ppt", ".pptx", ".pps", ".ppsx", ".odp"}

    def build_options(self, layout):
        self.info.setText("Needs LibreOffice installed. Select a file and press Delete to remove it from the list.")

    def load(self, paths):
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        skipped = [Path(p).name for p in paths if Path(p).suffix.lower() not in self.SUFFIXES]
        for p in paths:
            if Path(p).suffix.lower() in self.SUFFIXES:
                self.src = self.src or Path(p)
                self.grid.add(Path(p).name, str(p), icon)
        if skipped:
            raise pdfx.PdfxError("Not a presentation: " + ", ".join(skipped))

    def go(self):
        files = self.grid.values()
        if folder := self.ask_folder():
            self.run(lambda: pdfx.ppt_to_pdf(files, folder), lambda _: self.saved(folder))


class PdfToPptTool(PageTool):
    title, blurb, action = "PDF to PowerPoint", "Turn PDF pages into slides.", "Convert to PowerPoint"
    selectable = False
    MODES = [
        ("Editable (text stays text)", True),
        ("Exact look (pages as pictures)", False),
    ]

    def build_options(self, layout):
        self.group = QButtonGroup(self)
        for n, (label, editable) in enumerate(self.MODES):
            b = QRadioButton(label)
            b.setProperty("editable", editable)
            self.group.addButton(b, n)
            layout.addWidget(b)
        self.group.button(0).setChecked(True)
        self.group.buttonClicked.connect(self.mode_clicked)
        note = QLabel(
            "Editable works best on PDFs with real, selectable text. Complex layouts can shift, and "
            "scanned pages stay pictures. It needs LibreOffice."
        )
        note.setWordWrap(True)
        note.setObjectName("note")
        layout.addWidget(note)

    def on_show(self):
        """Grey out Editable while LibreOffice is missing. Re-checked on every visit and click."""
        have = pdfx.libreoffice_path() is not None
        editable = self.group.button(0)
        editable.setText(self.MODES[0][0] if have else "Editable (needs LibreOffice)")
        editable.setStyleSheet("" if have else "color: #a3a6ab;")
        if not have and editable.isChecked():
            self.group.button(1).setChecked(True)

    def mode_clicked(self, button):
        if button.property("editable") and not pdfx.libreoffice_path():
            ask_install_libreoffice(self)
        self.on_show()  # falls back to Exact look if LibreOffice is still missing

    def go(self):
        editable = self.group.checkedButton().property("editable")
        if out := self.ask_save(f"{self.src.stem}.pptx", "PowerPoint files (*.pptx)"):
            self.run(lambda: pdfx.pdf_to_ppt(self.src, out, editable=editable), self.saved)


class ImagesToPdfTool(Tool):
    title, blurb, action = "Image to PDF", "Turn JPG, PNG and other images into one PDF.", "Create PDF"
    multi, editable = True, True
    drop = "Drop images here"
    exts = "Images (*.jpg *.jpeg *.png *.gif *.bmp *.tif *.tiff *.webp)"
    SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}

    def build_options(self, layout):
        self.info.setText(
            "One page per image, in this order. Drag images to reorder them, or press Enter on one and use the "
            "arrow keys (Enter again to drop). Select an image and press Delete to remove it."
        )

    def load(self, paths):
        good = [p for p in paths if Path(p).suffix.lower() in self.SUFFIXES]
        items = []
        for p in good:
            self.src = self.src or Path(p)
            name = Path(p).name
            items.append(self.grid.add(name if len(name) <= 22 else name[:19] + "…", str(p)))
        self.grid.render_images(items, good)
        if skipped := [Path(p).name for p in paths if p not in good]:
            raise pdfx.PdfxError("Not a supported image: " + ", ".join(skipped))

    def go(self):
        files = self.grid.values()
        if out := self.ask_save("images.pdf"):
            self.run(lambda: pdfx.images_to_pdf(files, out), self.saved)


TOOLS = [MergeTool, OrganizeTool, SplitTool, WatermarkTool, CompressTool, PptTool, PdfToPptTool, ImagesToPdfTool]
