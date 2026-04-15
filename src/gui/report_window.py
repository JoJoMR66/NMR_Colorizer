"""
Fenêtre Rapport — NMR Colorizer

Spectre ¹H en SVG vectoriel + molécule SVG + nom de composé draggable.
Toutes les couleurs sont vectorielles et identiques à la fenêtre principale.
"""

import re
import io
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_svg import FigureCanvasSVG

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGraphicsView,
    QGraphicsScene, QGraphicsItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsTextItem, QPushButton,
    QLabel, QFileDialog, QSizePolicy, QMessageBox, QStyle
)
from PyQt5.QtWidgets import QStyleOptionGraphicsItem
from PyQt5.QtCore import Qt, QRectF, QByteArray, QPointF
from PyQt5.QtGui import (
    QPixmap, QImage, QPainter, QColor, QBrush,
    QPen, QFont, QTransform
)
from PyQt5.QtSvg import QGraphicsSvgItem, QSvgRenderer

try:
    from rdkit import Chem
    from rdkit.Chem import rdDepictor
    from rdkit.Chem.Draw import rdMolDraw2D
    RDKIT_OK = True
except ImportError:
    RDKIT_OK = False

MOL_SVG_W    = 700
MOL_SVG_H    = 280
HANDLE_SIZE  = 12


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_set(opts, attr, value):
    try:
        setattr(opts, attr, value)
    except AttributeError:
        pass


def _hex_to_rdkit(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def _force_transparent_bg(svg_text: str) -> str:
    svg_text = re.sub(
        r"<rect\s[^>]*fill=['\"]#(?:ffffff|000000|FFFFFF|000)['\"][^>]*/?>",
        "", svg_text, flags=re.IGNORECASE
    )
    svg_text = re.sub(
        r"background-color\s*:\s*#?(?:white|black|ffffff|000000)\s*;?",
        "", svg_text, flags=re.IGNORECASE
    )
    return svg_text


def _strip_svg_colors_report(svg_text: str, user_colors_hex: set = None) -> str:
    """
    Supprime les couleurs RDKit par défaut du SVG, mais garde les couleurs utilisateur.
    """
    import re
    
    if user_colors_hex is None:
        user_colors_hex = set()
    
    rdkit_default_colors = {
        '#A01EEF',  # I (purple)
        '#0000FF',  # N (blue)
        '#FF0000',  # O (red)
        '#33CCCC',  # S/F/Cl (cyan)
        '#00CC00',  # F
        '#CCCC00',  # S
    }
    
    def replace_color(match):
        hex_code = match.group(0).upper()
        
        # Ne pas remplacer blanc/noir/couleurs utilisateur
        if hex_code in ('#FFFFFF', '#000000') or hex_code in user_colors_hex:
            return match.group(0)
        
        # Remplacer couleurs RDKit par défaut par noir
        if hex_code in rdkit_default_colors:
            return '#000000'
        
        # Autres couleurs -> noir aussi
        return '#000000'
    
    svg_text = re.sub(r'#[0-9A-Fa-f]{6}', replace_color, svg_text)
    return svg_text


# ---------------------------------------------------------------------------
# Poignée de redimensionnement
# ---------------------------------------------------------------------------

class _ResizeHandle(QGraphicsRectItem):
    def __init__(self, parent_item, corner: str):
        super().__init__(-HANDLE_SIZE/2, -HANDLE_SIZE/2,
                         HANDLE_SIZE, HANDLE_SIZE, parent_item)
        self._corner      = corner
        self._parent_item = parent_item
        self.setBrush(QBrush(QColor("#2196F3")))
        self.setPen(QPen(QColor("#0D47A1"), 1))
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setCursor(Qt.SizeFDiagCursor if corner in ("TL", "BR")
                       else Qt.SizeBDiagCursor)
        self.setZValue(20)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start  = event.scenePos()
            self._orig_scale  = (self._parent_item._scale_x,
                                 self._parent_item._scale_y)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        delta = event.scenePos() - self._drag_start
        sx0, sy0 = self._orig_scale
        bw = self._parent_item._base_w
        bh = self._parent_item._base_h
        if bw <= 0 or bh <= 0:
            return
        if self._corner == "BR":
            ns = max(0.1, sx0 + delta.x() / bw)
        elif self._corner == "BL":
            ns = max(0.1, sx0 - delta.x() / bw)
        elif self._corner == "TR":
            ns = max(0.1, sx0 + delta.x() / bw)
        else:
            ns = max(0.1, sx0 - delta.x() / bw)
        self._parent_item.set_scale(ns, ns)
        event.accept()


# ---------------------------------------------------------------------------
# Item SVG générique (molécule ou spectre) — draggable + resizable + rotatable
# ---------------------------------------------------------------------------

class _SvgItem(QGraphicsSvgItem):
    def __init__(self, svg_bytes: bytes, movable: bool = True,
                 resizable: bool = True):
        super().__init__()
        self._renderer = QSvgRenderer(QByteArray(svg_bytes))
        self.setSharedRenderer(self._renderer)
        flags = QGraphicsItem.ItemSendsGeometryChanges
        if movable:
            flags |= QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
        self.setFlags(flags)
        self.setAcceptHoverEvents(movable)
        self._rotation_deg = 0.0
        self._scale_x      = 1.0
        self._scale_y      = 1.0
        self._base_w       = self.boundingRect().width()
        self._base_h       = self.boundingRect().height()
        self._handles      = {}
        if resizable:
            for corner in ("TL", "TR", "BL", "BR"):
                h = _ResizeHandle(self, corner)
                self._handles[corner] = h
            self._update_handles()

    def _update_handles(self):
        w = self._base_w * self._scale_x
        h = self._base_h * self._scale_y
        positions = {
            "TL": QPointF(0, 0),
            "TR": QPointF(w, 0),
            "BL": QPointF(0, h),
            "BR": QPointF(w, h),
        }
        for corner, handle in self._handles.items():
            handle.setPos(positions[corner])

    def set_scale(self, sx: float, sy: float):
        self._scale_x = sx
        self._scale_y = sy
        self._apply_transform()
        self._update_handles()

    def rotate_by(self, deg: float):
        self._rotation_deg += deg
        self._apply_transform()

    def hide_handles(self):
        """Masque tous les poignées de redimensionnement."""
        for handle in self._handles.values():
            handle.hide()

    def show_handles(self):
        """Affiche tous les poignées de redimensionnement."""
        for handle in self._handles.values():
            handle.show()

    def _apply_transform(self):
        cx = self._base_w / 2
        cy = self._base_h / 2
        t  = QTransform()
        t.translate(cx, cy)
        t.rotate(self._rotation_deg)
        t.scale(self._scale_x, self._scale_y)
        t.translate(-cx, -cy)
        self.setTransform(t)

    def hoverEnterEvent(self, event):
        self.setCursor(Qt.SizeAllCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget):
        """Peint le SVG sans le rectangle de sélection."""
        opt = QStyleOptionGraphicsItem(option)
        opt.state &= ~QStyle.State_Selected
        super().paint(painter, opt, widget)


# ---------------------------------------------------------------------------
# Item texte draggable + redimensionnable
# ---------------------------------------------------------------------------

class _TextItem(QGraphicsTextItem):
    """Nom de composé draggable avec poignée de redimensionnement."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setFont(QFont("Arial", 18, QFont.Bold))
        self.setDefaultTextColor(QColor("#111111"))
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self._font_size = 18

        # Poignée BR
        self._handle = _TextResizeHandle(self)
        self._update_handle()

    def _update_handle(self):
        br = self.boundingRect()
        self._handle.setPos(br.width(), br.height())

    def set_font_size(self, size: int):
        self._font_size = max(6, size)
        f = self.font()
        f.setPointSize(self._font_size)
        self.setFont(f)
        self._update_handle()

    def hoverEnterEvent(self, event):
        self.setCursor(Qt.SizeAllCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget):
        """Peint le texte sans le rectangle de sélection."""
        # Crée une copie de l'option sans la flag de sélection
        opt = QStyleOptionGraphicsItem(option)
        opt.state &= ~QStyle.State_Selected
        super().paint(painter, opt, widget)

    def hide_handle(self):
        """Masque la poignée de redimensionnement."""
        self._handle.hide()

    def show_handle(self):
        """Affiche la poignée de redimensionnement."""
        self._handle.show()


class _TextResizeHandle(QGraphicsRectItem):
    def __init__(self, text_item: _TextItem):
        super().__init__(-HANDLE_SIZE/2, -HANDLE_SIZE/2,
                         HANDLE_SIZE, HANDLE_SIZE, text_item)
        self._text_item  = text_item
        self.setBrush(QBrush(QColor("#FF5722")))
        self.setPen(QPen(QColor("#BF360C"), 1))
        self.setCursor(Qt.SizeFDiagCursor)
        self.setZValue(20)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start_y   = event.scenePos().y()
            self._start_size = self._text_item._font_size
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        dy       = event.scenePos().y() - self._start_y
        new_size = int(self._start_size + dy / 3)
        self._text_item.set_font_size(new_size)
        self._text_item._update_handle()
        event.accept()


# ---------------------------------------------------------------------------
# Rendu spectre en SVG vectoriel
# ---------------------------------------------------------------------------

def _render_spectrum_svg(ppm, intensites, pick_rects: dict, xlim_range=None, ylim_range=None) -> bytes:
    """
    Génère le spectre ¹H en SVG vectoriel matplotlib.
    Les couleurs sont exactement les mêmes qu'en fenêtre principale.
    """
    fig, ax = plt.subplots(figsize=(14, 3.5))

    ax.plot(ppm, intensites, color="black", linewidth=0.6, zorder=3)
    ax.invert_xaxis()
    ax.set_xlabel("δ ¹H (ppm)", fontsize=9)
    ax.yaxis.set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_linewidth(0.8)

    # Région du spectre : xlim_range fourni ou vue ajustée aux pics
    if xlim_range is not None:
        ax.set_xlim(xlim_range[0], xlim_range[1])
    else:
        seuil   = np.max(np.abs(intensites)) * 0.01
        indices = np.where(np.abs(intensites) > seuil)[0]
        if len(indices) > 0:
            ppm_lo = ppm[indices].min()
            ppm_hi = ppm[indices].max()
            marge  = (ppm_hi - ppm_lo) * 0.04
            ax.set_xlim(ppm_hi + marge, ppm_lo - marge)

    # Intensité du spectre : ylim_range fourni ou calculé
    if ylim_range is not None:
        ax.set_ylim(ylim_range[0], ylim_range[1])
    else:
        pos_max = (float(np.max(intensites[intensites > 0]))
                   if np.any(intensites > 0) else float(np.max(np.abs(intensites))))
        ax.set_ylim(0.0, pos_max * 1.15)  # baseline fixe à 0

    # Rectangles colorés
    for dc_key, rect_list in pick_rects.items():
        for dr in rect_list:
            x_left  = dr.x_right
            width   = dr.width
            height  = abs(dr.height)
            y_rect  = 0 if dr.height >= 0 else dr.height
            couleur = dr.couleur

            if dr.couleur_droite is None:
                ax.add_patch(mpatches.Rectangle(
                    (x_left, y_rect), width, height,
                    linewidth=1.0, edgecolor=couleur,
                    facecolor=couleur, alpha=1.0, zorder=2
                ))
            else:
                half = width / 2
                for i, col in enumerate([couleur, dr.couleur_droite]):
                    ax.add_patch(mpatches.Rectangle(
                        (x_left + i*half, y_rect), half, height,
                        linewidth=0, facecolor=col, alpha=1.0, zorder=2
                    ))
                ax.add_patch(mpatches.Rectangle(
                    (x_left, y_rect), width, height,
                    linewidth=1.0, edgecolor="black",
                    facecolor="none", zorder=3
                ))

    fig.patch.set_facecolor("white")
    fig.tight_layout(pad=0.3)

    # Rendu en SVG
    buf = io.BytesIO()
    canvas = FigureCanvasSVG(fig)
    canvas.print_svg(buf)
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Rendu SVG molécule
# ---------------------------------------------------------------------------

def _render_mol_svg(mol, attributions: dict) -> bytes:
    if mol is None or not RDKIT_OK:
        return b""

    try:
        mol_display = Chem.RemoveHs(mol)
    except Exception:
        mol_display = mol

    try:
        rdDepictor.Compute2DCoords(mol_display)
    except Exception:
        pass

    highlight_atoms = {}
    highlight_bonds = {}

    for atom_idx_h, (dc_key, hex_color) in attributions.items():
        rdcolor  = _hex_to_rdkit(hex_color)
        atom_h   = mol.GetAtomWithIdx(atom_idx_h)

        if atom_h.GetSymbol() == "H":
            for nb in atom_h.GetNeighbors():
                if nb.GetSymbol() == "C":
                    c_disp = _find_in_display(mol, mol_display, nb.GetIdx())
                    if c_disp is not None:
                        highlight_atoms[c_disp] = rdcolor
                        bond = mol.GetBondBetweenAtoms(atom_idx_h, nb.GetIdx())
                        if bond:
                            b_disp = _find_bond_in_display(
                                mol_display, nb.GetIdx(), None
                            )
        else:
            c_disp = _find_in_display(mol, mol_display, atom_idx_h)
            if c_disp is not None:
                highlight_atoms[c_disp] = rdcolor

    drawer = rdMolDraw2D.MolDraw2DSVG(MOL_SVG_W, MOL_SVG_H)
    opts   = drawer.drawOptions()
    _safe_set(opts, "bondLineWidth",       2.0)
    _safe_set(opts, "clearBackground",     False)
    _safe_set(opts, "addStereoAnnotation", True)
    _safe_set(opts, "addAtomIndices",      False)
    _safe_set(opts, "padding",             0.12)
    
    # Force all atoms to black (override RDKit defaults)
    _black = (0.0, 0.0, 0.0)
    black_palette = {
        "C": _black, "H": _black, "N": _black, "O": _black, "S": _black,
        "P": _black, "F": _black, "Cl": _black, "Br": _black, "I": _black,
        "B": _black, "Si": _black, "Se": _black, "As": _black
    }
    try:
        opts.updateAtomPalette(black_palette)
    except Exception:
        pass

    try:
        rdMolDraw2D.PrepareMolForDrawing(mol_display)
    except Exception:
        pass

    try:
        if highlight_atoms:
            drawer.DrawMolecule(
                mol_display,
                highlightAtoms=list(highlight_atoms.keys()),
                highlightAtomColors=highlight_atoms,
                highlightBonds=[],
                highlightBondColors={},
            )
        else:
            drawer.DrawMolecule(mol_display)
    except Exception as e:
        print(f"Mol SVG draw error: {e}")
        try:
            drawer.DrawMolecule(mol_display)
        except Exception:
            return b""

    drawer.FinishDrawing()
    svg_text = drawer.GetDrawingText()
    svg_text = _force_transparent_bg(svg_text)
    
    # Extract user-assigned colors to preserve them
    user_colors_hex = set()
    for atom_idx, rgb_tuple in highlight_atoms.items():
        if isinstance(rgb_tuple, tuple) and len(rgb_tuple) == 3:
            r, g, b = rgb_tuple
            hex_color = f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
            user_colors_hex.add(hex_color.upper())
    
    svg_text = _strip_svg_colors_report(svg_text, user_colors_hex)
    return svg_text.encode("utf-8")


def _find_in_display(mol_h, mol_display, idx_in_h: int):
    atom = mol_h.GetAtomWithIdx(idx_in_h)
    if atom.GetSymbol() == "H":
        return None
    heavy_before = sum(
        1 for a in mol_h.GetAtoms()
        if a.GetIdx() < idx_in_h and a.GetSymbol() != "H"
    )
    return heavy_before if heavy_before < mol_display.GetNumAtoms() else None


def _find_bond_in_display(mol_display, idx_a, idx_b):
    return None   # simplifié


# ---------------------------------------------------------------------------
# Fenêtre rapport
# ---------------------------------------------------------------------------

class ReportWindow(QDialog):

    def __init__(self, parent, ppm, intensites,
                 pick_rects: dict,
                 mol=None, attributions: dict = None,
                 compound_name: str = "",
                 xlim_range=None, ylim_range=None):
        super().__init__(parent)
        self.setWindowTitle("NMR Colorizer — Rapport")
        self.setMinimumSize(1100, 650)
        self.setModal(False)

        self._ppm          = ppm
        self._intensites   = intensites
        self._pick_rects   = pick_rects
        self._mol          = mol
        self._attributions = attributions or {}
        self._compound_name = compound_name
        self._xlim_range   = xlim_range   # None = spectre complet
        self._ylim_range   = ylim_range   # None = intensité initiale
        self._mol_item     = None
        self._text_item    = None

        self._build_ui()
        self._render_scene()

    # -------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        def _btn(label, slot, tip=""):
            b = QPushButton(label)
            b.setFixedHeight(26)
            b.setFont(QFont("Arial", 8))
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(slot)
            toolbar.addWidget(b)

        _btn("🔍 +",         self._zoom_in)
        _btn("🔍 −",         self._zoom_out)
        _btn("⊡ Ajuster",    self._fit_view)
        toolbar.addWidget(QLabel(" | "))
        _btn("↺ −15°",      lambda: self._rotate_mol(-15))
        _btn("↻ +15°",      lambda: self._rotate_mol(+15))
        toolbar.addWidget(QLabel(" | "))
        _btn("💾 Exporter PNG", self._export_png)
        _btn("✕ Fermer",       self.close)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._scene = QGraphicsScene(self)
        self._view  = _ReportView(self._scene, self)
        layout.addWidget(self._view)

        hint = QLabel(
            "Glisser les éléments pour les repositionner  |  "
            "Coins bleus : redimensionner la molécule  |  "
            "Coin orange : taille du texte  |  "
            "Molette : zoom vue"
        )
        hint.setFont(QFont("Arial", 7))
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

    # -------------------------------------------------------------------
    # Rendu scène
    # -------------------------------------------------------------------

    def _render_scene(self):
        self._scene.clear()
        self._mol_item  = None
        self._text_item = None

        # 1. Spectre SVG vectoriel en fond (non draggable)
        spec_svg = _render_spectrum_svg(
            self._ppm, self._intensites, self._pick_rects,
            xlim_range=self._xlim_range,
            ylim_range=self._ylim_range
        )
        spec_item = _SvgItem(spec_svg, movable=False, resizable=False)
        spec_item.setZValue(0)
        self._scene.addItem(spec_item)

        spec_w = spec_item.boundingRect().width()
        spec_h = spec_item.boundingRect().height()

        # 2. Molécule SVG en overlay
        if self._mol is not None and RDKIT_OK:
            mol_svg = _render_mol_svg(self._mol, self._attributions)
            if mol_svg:
                self._mol_item = _SvgItem(mol_svg, movable=True, resizable=True)
                self._mol_item.setZValue(2)
                mw = self._mol_item.boundingRect().width()
                mh = self._mol_item.boundingRect().height()
                # Positionne en haut à gauche avec une marge
                self._mol_item.setPos(20, 10)
                self._scene.addItem(self._mol_item)

        # 3. Nom du composé
        if self._compound_name:
            self._text_item = _TextItem(self._compound_name)
            self._text_item.setZValue(3)
            # En bas à droite du spectre
            tw = self._text_item.boundingRect().width()
            th = self._text_item.boundingRect().height()
            self._text_item.setPos(spec_w - tw - 20, spec_h - th - 10)
            self._scene.addItem(self._text_item)

        self._scene.setSceneRect(self._scene.itemsBoundingRect())
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    # -------------------------------------------------------------------
    # Contrôles
    # -------------------------------------------------------------------

    def _zoom_in(self):   self._view.scale(1.2, 1.2)
    def _zoom_out(self):  self._view.scale(1/1.2, 1/1.2)
    def _fit_view(self):
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _rotate_mol(self, deg: float):
        if self._mol_item:
            self._mol_item.rotate_by(deg)

    # -------------------------------------------------------------------
    # Export PNG
    # -------------------------------------------------------------------

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter le rapport", "rapport_nmr.png",
            "Images PNG (*.png)"
        )
        if not path:
            return

        # Masque tous les poignées de redimensionnement pour un export clean
        if self._mol_item:
            self._mol_item.hide_handles()
        if self._text_item:
            self._text_item.hide_handle()

        try:
            scene_rect = self._scene.sceneRect()
            scale      = 2.0

            img = QImage(
                int(scene_rect.width()  * scale),
                int(scene_rect.height() * scale),
                QImage.Format_ARGB32
            )
            img.fill(Qt.white)

            painter = QPainter(img)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            self._scene.render(
                painter,
                QRectF(0, 0, scene_rect.width()*scale, scene_rect.height()*scale),
                scene_rect
            )
            painter.end()

            if img.save(path, "PNG"):
                QMessageBox.information(self, "Export", f"Rapport exporté :\n{path}")
            else:
                QMessageBox.warning(self, "Export", "Erreur lors de l'export.")
        finally:
            # Réaffiche les poignées après l'export
            if self._mol_item:
                self._mol_item.show_handles()
            if self._text_item:
                self._text_item.show_handle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_scene"):
            self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)


# ---------------------------------------------------------------------------
# Vue
# ---------------------------------------------------------------------------

class _ReportView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        from PyQt5.QtGui import QPainter
        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.SmoothPixmapTransform
            | QPainter.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.NoDrag)
        self.setBackgroundBrush(QBrush(QColor("#e0e0e0")))
        self.setFrameShape(self.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self.scale(factor, factor)