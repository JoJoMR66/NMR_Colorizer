import numpy as np
import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import RectangleSelector
import matplotlib.patches as patches
import matplotlib.gridspec as gridspec
from collections import defaultdict
from PyQt5.QtWidgets import QColorDialog
from PyQt5.QtGui import QColor

_GS_LEFT         = 0.04
_GS_RIGHT        = 0.98
_GS_WIDTH_RATIOS = [1, 6]
_GS_WSPACE       = 0.02


def find_multiplet_boundaries(ppm, intensites, dH,
                               seuil_relatif=0.015, marge_ppm=0.008):
    seuil_bruit = np.max(np.abs(intensites)) * seuil_relatif
    fenetre     = 80
    idx_centre  = np.argmin(np.abs(ppm - dH))
    idx_debut   = max(0, idx_centre - fenetre)
    idx_fin     = min(len(intensites) - 1, idx_centre + fenetre)
    idx_max     = idx_debut + np.argmax(np.abs(intensites[idx_debut:idx_fin + 1]))
    int_max     = intensites[idx_max]

    idx_g = idx_max
    while idx_g > 0 and np.abs(intensites[idx_g]) > seuil_bruit:
        idx_g -= 1
    idx_d = idx_max
    while idx_d < len(intensites) - 1 and np.abs(intensites[idx_d]) > seuil_bruit:
        idx_d += 1

    ppm_g  = ppm[idx_g] + marge_ppm
    ppm_d  = ppm[idx_d] - marge_ppm
    centre = dH
    demi   = max(abs(centre - ppm_g), abs(centre - ppm_d))
    if demi < 0.015:
        demi = 0.015
    return centre, demi, int_max


class DraggableRect:
    ALPHA = 0.45

    def __init__(self, ax, centre, demi_largeur, height, couleur,
                 couleur_droite=None, dc_key=None):
        self.ax             = ax
        self.centre         = centre
        self.demi_g         = demi_largeur
        self.demi_d         = demi_largeur
        self.height         = height
        self.couleur        = couleur
        self.couleur_droite = couleur_droite
        self.dc_key         = dc_key   # identifiant du groupe (δC arrondi)
        self.y_rect         = 0 if height >= 0 else height
        self.hauteur        = abs(height)
        self._mode          = None
        self._x_press       = None
        self._demi_press    = None
        self._build_patches()

    @property
    def x_left(self):
        return self.centre + self.demi_g

    @property
    def x_right(self):
        return self.centre - self.demi_d

    @property
    def width(self):
        return self.demi_g + self.demi_d

    def _edge_tol(self):
        return max(self.width * 0.15, 0.02)

    def _build_patches(self):
        xl = self.x_right
        w  = self.width
        if self.couleur_droite is None:
            self.patch_main = patches.Rectangle(
                (xl, self.y_rect), w, self.hauteur,
                linewidth=1.5, edgecolor=self.couleur,
                facecolor=self.couleur, alpha=self.ALPHA, zorder=2
            )
            self.patch_half_l = None
            self.patch_half_r = None
            self.ax.add_patch(self.patch_main)
        else:
            self.patch_half_l = patches.Rectangle(
                (xl, self.y_rect), w / 2, self.hauteur,
                linewidth=0, facecolor=self.couleur,
                alpha=1.0, zorder=2
            )
            self.patch_half_r = patches.Rectangle(
                (xl + w / 2, self.y_rect), w / 2, self.hauteur,
                linewidth=0, facecolor=self.couleur_droite,
                alpha=1.0, zorder=2
            )
            self.patch_main = patches.Rectangle(
                (xl, self.y_rect), w, self.hauteur,
                linewidth=1.5, edgecolor="black",
                facecolor="none", zorder=3
            )
            self.ax.add_patch(self.patch_half_l)
            self.ax.add_patch(self.patch_half_r)
            self.ax.add_patch(self.patch_main)

    def set_color(self, couleur):
        """Change la couleur du rectangle en direct."""
        self.couleur = couleur
        if self.couleur_droite is None:
            self.patch_main.set_facecolor(couleur)
            self.patch_main.set_edgecolor(couleur)
        else:
            self.patch_half_l.set_facecolor(couleur)

    def _update(self):
        xl = self.x_right
        w  = self.width
        self.patch_main.set_x(xl)
        self.patch_main.set_width(w)
        if self.couleur_droite is not None:
            self.patch_half_l.set_x(xl)
            self.patch_half_l.set_width(w / 2)
            self.patch_half_r.set_x(xl + w / 2)
            self.patch_half_r.set_width(w / 2)

    def _detect_zone(self, x):
        tol = self._edge_tol()
        if abs(x - self.x_left) <= tol:
            return "left"
        if abs(x - self.x_right) <= tol:
            return "right"
        if self.x_right <= x <= self.x_left:
            return "inside"
        return None

    def contains(self, x, y):
        return (self.x_right <= x <= self.x_left
                and self.y_rect <= y <= self.y_rect + self.hauteur)

    def on_press(self, x, y):
        if not self.contains(x, y):
            return False
        zone = self._detect_zone(x)
        if zone in ("left", "right"):
            self._mode       = zone
            self._x_press    = x
            self._demi_press = self.demi_g if zone == "left" else self.demi_d
            return True
        return False

    def on_motion(self, x):
        if self._mode is None:
            return
        dx = x - self._x_press
        if self._mode == "left":
            self.demi_g = max(0.01, self._demi_press + dx)
        elif self._mode == "right":
            self.demi_d = max(0.01, self._demi_press - dx)
        self._update()

    def on_release(self):
        self._mode = None

    def get_cursor(self, x, y):
        if not self.contains(x, y):
            return None
        zone = self._detect_zone(x)
        return "resize_horizontal" if zone in ("left", "right") else "arrow"

    def remove_from_ax(self):
        """Supprime les patches de l'axe."""
        for p in [self.patch_main, self.patch_half_l, self.patch_half_r]:
            if p is not None:
                try:
                    p.remove()
                except Exception:
                    pass


class SpectrumCanvas(FigureCanvas):

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(10, 3))
        super().__init__(self.fig)
        self.setParent(parent)

        # Gridspec aligné avec le canvas 2D
        gs = gridspec.GridSpec(
            1, 2,
            figure=self.fig,
            width_ratios=_GS_WIDTH_RATIOS,
            wspace=_GS_WSPACE,
            left=_GS_LEFT, right=_GS_RIGHT,
            top=0.88, bottom=0.18
        )
        self._ax_dummy = self.fig.add_subplot(gs[0, 0])
        self._ax_dummy.axis("off")
        self.ax = self.fig.add_subplot(gs[0, 1])

        self.ppm         = None
        self.intensites  = None
        self.rects       = []          # DraggableRect (mode tableau HSQC)
        self.pick_rects  = {}          # {dc_key: [DraggableRect]} (mode pick)
        self._active     = None
        self._syncing    = False
        self._selector   = None
        self._zoom_stack = []
        self._xlim_cid   = None
        self._y_min      = 0
        self._y_max      = 1

        # Croix
        self._vline = None

        # Callbacks
        self.on_xlim_changed_cb   = None
        self.on_crosshair_move_cb = None
        # Callback pour notifier la couleur changée: (dc_key, new_color)
        self.on_color_changed_cb  = None
        # Callback clic sur rectangle (pour attribution molécule): (dc_key)
        self.on_rect_clicked_cb   = None
        # Callback clic droit sur spectre (proton mobile): (dH)
        self.on_mobile_proton_cb  = None

        self._connect_xlim_cb()

        self.mpl_connect("button_press_event",   self._on_press)
        self.mpl_connect("motion_notify_event",  self._on_motion)
        self.mpl_connect("button_release_event", self._on_release)
        self.mpl_connect("scroll_event",         self._on_scroll)

    # -------------------------------------------------------------------
    # Callback xlim
    # -------------------------------------------------------------------

    def _connect_xlim_cb(self):
        if self._xlim_cid is not None:
            try:
                self.ax.callbacks.disconnect(self._xlim_cid)
            except Exception:
                pass
        self._xlim_cid = self.ax.callbacks.connect(
            "xlim_changed", self._on_xlim_changed
        )

    # -------------------------------------------------------------------
    # Croix
    # -------------------------------------------------------------------

    def _init_crosshair(self):
        self._vline, = self.ax.plot(
            [], [], color="gray", linewidth=0.7,
            linestyle="--", zorder=10, visible=False
        )

    def update_crosshair(self, x_ppm):
        if self._vline is None or self.ppm is None:
            return
        if x_ppm is None:
            self._vline.set_visible(False)
        else:
            ylim = self.ax.get_ylim()
            self._vline.set_data([x_ppm, x_ppm], [ylim[0], ylim[1]])
            self._vline.set_visible(True)
        self.draw_idle()

    # -------------------------------------------------------------------
    # Chargement spectre
    # -------------------------------------------------------------------

    def plot(self, ppm, intensites, groupes=None, couleurs=None):
        self.ppm        = ppm
        self.intensites = intensites
        self.rects      = []
        self.pick_rects = {}
        self._active    = None
        self._zoom_stack = []

        self.ax.cla()
        self._connect_xlim_cb()
        self._vline = None

        self.ax.plot(ppm, intensites, color="black", linewidth=0.8, zorder=3)
        self.ax.invert_xaxis()
        self.ax.set_xlabel("δ ¹H (ppm)", fontsize=9)
        self.ax.set_ylabel("Intensité", fontsize=9)
        self.ax.set_title("Spectre ¹H", fontsize=10)

        self._x_min = ppm.min()
        self._x_max = ppm.max()
        # Spectre ¹H : baseline = 0, pas d'intensités négatives affichées
        pos_max     = float(np.max(intensites[intensites > 0])) if np.any(intensites > 0) else float(np.max(np.abs(intensites)))
        self._y_max = pos_max * 1.15
        self._y_min = 0.0   # baseline fixe

        self.ax.set_xlim(self._x_max, self._x_min)
        self.ax.set_ylim(0.0, self._y_max)

        if groupes and couleurs:
            self._build_rects_from_table(groupes, couleurs)

        self._init_crosshair()
        self._init_selector()
        self.draw()

    def _build_rects_from_table(self, groupes, couleurs):
        """Mode tableau HSQC : construit les rects depuis le groupeur."""
        dH_to_groups = defaultdict(list)
        for gid, info in groupes.items():
            for dH in info["protons"]:
                dH_to_groups[round(dH, 4)].append(gid)

        deja = set()
        for gid, info in groupes.items():
            couleur = couleurs[gid]
            for dH in info["protons"]:
                key      = round(dH, 4)
                partages = dH_to_groups[key]
                if len(partages) == 2 and key in deja:
                    continue
                centre, demi, int_max = find_multiplet_boundaries(
                    self.ppm, self.intensites, dH
                )
                if len(partages) == 1:
                    dr = DraggableRect(self.ax, centre, demi, int_max, couleur)
                else:
                    deja.add(key)
                    dr = DraggableRect(self.ax, centre, demi, int_max,
                                       couleur, couleurs[partages[1]])
                self.rects.append(dr)

    # -------------------------------------------------------------------
    # Mode pick peaking : ajout dynamique de groupes
    # -------------------------------------------------------------------

    def add_rect_group(self, dH_list: list, couleur: str, dc_key: float):
        """
        Ajoute des rectangles colorés pour un groupe de protons (mode pick).
        dH_list : liste de δH du groupe
        couleur  : couleur hex
        dc_key   : identifiant du groupe (δC arrondi)
        """
        if self.ppm is None or self.intensites is None:
            return

        # Supprime les anciens rectangles du même groupe s'ils existent
        if dc_key in self.pick_rects:
            for old_rect in self.pick_rects[dc_key]:
                try:
                    old_rect.remove()
                except Exception:
                    pass

        group_rects = []
        for dH in dH_list:
            centre, demi, int_max = find_multiplet_boundaries(
                self.ppm, self.intensites, dH
            )
            dr = DraggableRect(
                self.ax, centre, demi, int_max, couleur, dc_key=dc_key
            )
            group_rects.append(dr)

        self.pick_rects[dc_key] = group_rects
        self.draw()


    def remove_single_rect(self, dc_key, dH: float):
        """
        Supprime uniquement le rectangle correspondant à un dH précis
        dans un groupe dc_key. Si le groupe devient vide, le supprime entièrement.
        """
        if dc_key not in self.pick_rects:
            return
        group = self.pick_rects[dc_key]
        to_remove = None
        for dr in group:
            if abs(dr.centre - dH) < 0.01:
                to_remove = dr
                break
        if to_remove is not None:
            to_remove.remove_from_ax()
            group.remove(to_remove)
        if not group:
            del self.pick_rects[dc_key]
        self.draw()

    def remove_rect_group(self, dc_key: float):
        """Supprime un groupe de rectangles."""
        if dc_key in self.pick_rects:
            for dr in self.pick_rects[dc_key]:
                dr.remove_from_ax()
            del self.pick_rects[dc_key]
            self.draw()

    def update_group_color(self, dc_key: float, couleur: str):
        """Met à jour la couleur de tous les rects d'un groupe."""
        if dc_key in self.pick_rects:
            for dr in self.pick_rects[dc_key]:
                dr.set_color(couleur)
            self.draw()


    def update_rect_position(self, dc_key: float, new_dH: float):
        """Met à jour la position d'un rectangle après édition dans le tableau."""
        if dc_key not in self.pick_rects or self.ppm is None:
            return
        for dr in self.pick_rects[dc_key]:
            centre, demi, int_max = find_multiplet_boundaries(
                self.ppm, self.intensites, new_dH
            )
            dr.centre = centre
            dr.demi_g = demi
            dr.demi_d = demi
            dr.height = int_max
            dr.y_rect  = 0 if int_max >= 0 else int_max
            dr.hauteur = abs(int_max)
            dr._update()
        self.draw()

    def clear_pick_rects(self):
        """Efface tous les rectangles du mode pick."""
        for dc_key in list(self.pick_rects.keys()):
            self.remove_rect_group(dc_key)

    def _all_rects(self):
        """Retourne tous les rectangles (tableau + pick)."""
        all_r = list(self.rects)
        for group in self.pick_rects.values():
            all_r.extend(group)
        return all_r

    # -------------------------------------------------------------------
    # Zoom
    # -------------------------------------------------------------------

    def _init_selector(self):
        if self._selector:
            self._selector.set_active(False)
        self._selector = RectangleSelector(
            self.ax, self._on_zoom_select,
            useblit=True, button=[1],
            minspanx=5, minspany=5,
            spancoords="pixels", interactive=False,
            props=dict(facecolor="lightblue", alpha=0.25,
                       edgecolor="steelblue", linewidth=1)
        )

    def _on_zoom_select(self, eclick, erelease):
        x1, x2 = eclick.xdata, erelease.xdata
        if None in (x1, x2) or abs(x1 - x2) < 0.001:
            return
        self._zoom_stack.append(self.ax.get_xlim())
        self.ax.set_xlim(max(x1, x2), min(x1, x2))
        self.draw()

    def dezoom(self):
        if self._zoom_stack:
            self.ax.set_xlim(self._zoom_stack.pop())
        else:
            self.ax.set_xlim(self._x_max, self._x_min)
        self.draw()

    def reset_view(self):
        self._zoom_stack = []
        if self.ppm is None:
            return
        self.ax.set_xlim(self._x_max, self._x_min)
        self.ax.set_ylim(0.0, self._y_max)   # baseline toujours à 0
        self.draw()

    def zoom_to_peaks(self):
        if self.intensites is None:
            return
        seuil   = np.max(np.abs(self.intensites)) * 0.01
        indices = np.where(np.abs(self.intensites) > seuil)[0]
        if len(indices) == 0:
            return
        lo    = self.ppm[indices].min()
        hi    = self.ppm[indices].max()
        marge = (hi - lo) * 0.05
        self._zoom_stack.append(self.ax.get_xlim())
        self.ax.set_xlim(hi + marge, lo - marge)
        self.draw()

    # -------------------------------------------------------------------
    # Synchro
    # -------------------------------------------------------------------

    def _on_xlim_changed(self, ax):
        if self._syncing:
            return
        if self.on_xlim_changed_cb:
            self.on_xlim_changed_cb(ax.get_xlim())

    def sync_xlim(self, xlim):
        if self._syncing or self.ppm is None:
            return
        self._syncing = True
        self.ax.set_xlim(xlim)
        self.draw()
        self._syncing = False

    # -------------------------------------------------------------------
    # Export
    # -------------------------------------------------------------------

    def export_png(self, filepath: str, xlim=None):
        """
        Exporte le spectre en PNG.
        xlim : tuple (xmax, xmin) en ppm pour restreindre la région exportée.
               None = vue complète.
        """
        # Sauvegarde la vue courante
        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()

        # Applique la région si demandée
        if xlim is not None:
            self.ax.set_xlim(xlim)

        self.ax.set_title("")
        self.ax.set_ylabel("")
        self.ax.yaxis.set_visible(False)
        for spine in ["left", "top", "right"]:
            self.ax.spines[spine].set_visible(False)
        self.fig.savefig(filepath, dpi=300, bbox_inches="tight",
                         facecolor="white")
        # Restaure
        self.ax.set_title("Spectre ¹H", fontsize=10)
        self.ax.set_ylabel("Intensité", fontsize=9)
        self.ax.yaxis.set_visible(True)
        for spine in ["left", "top", "right"]:
            self.ax.spines[spine].set_visible(True)
        self.ax.set_xlim(cur_xlim)
        self.ax.set_ylim(cur_ylim)
        self.draw()

    def get_current_xlim(self):
        """Retourne les limites ppm actuellement affichées."""
        return self.ax.get_xlim()

    def get_current_ylim(self):
        """Retourne les limites d'intensité actuellement affichées."""
        return self.ax.get_ylim()

    # -------------------------------------------------------------------
    # Événements souris
    # -------------------------------------------------------------------


    def _snap_to_1d_peak(self, x_click: float) -> float:
        """Snape au maximum local le plus proche du clic sur le spectre 1D."""
        if self.ppm is None or self.intensites is None:
            return x_click
        from scipy.signal import find_peaks
        abs_int = np.abs(self.intensites)
        seuil   = np.max(abs_int) * 0.02
        peaks, _ = find_peaks(abs_int, height=seuil, distance=3)
        if len(peaks) == 0:
            return x_click
        peak_ppms = self.ppm[peaks]
        idx = np.argmin(np.abs(peak_ppms - x_click))
        return float(peak_ppms[idx])

    def _on_press(self, event):
        if event.inaxes != self.ax or event.xdata is None:
            return

        # Clic DROIT -> proton mobile (NH2, OH...) sans delta C
        if event.button == 3:
            dH = self._snap_to_1d_peak(event.xdata)
            if self.on_mobile_proton_cb:
                self.on_mobile_proton_cb(dH)
            return

        # Double-clic gauche sur un rectangle -> color picker
        if event.dblclick and event.button == 1:
            for dr in reversed(self._all_rects()):
                if dr.contains(event.xdata, event.ydata) and dr.dc_key is not None:
                    self._open_color_picker(dr)
                    return

        # Clic simple gauche : resize si sur un bord
        if event.button == 1:
            for dr in reversed(self._all_rects()):
                if dr.contains(event.xdata, event.ydata):
                    # Notifie pour attribution molécule
                    if dr.dc_key is not None and self.on_rect_clicked_cb:
                        self.on_rect_clicked_cb(dr.dc_key)
                if dr.on_press(event.xdata, event.ydata):
                    self._active = dr
                    if self._selector:
                        self._selector.set_active(False)
                    break

    def _open_color_picker(self, dr: DraggableRect):
        """Ouvre le color picker Qt et met à jour la couleur en direct."""
        initial = QColor(dr.couleur)
        color   = QColorDialog.getColor(
            initial, None, "Choisir une couleur",
            QColorDialog.ShowAlphaChannel
        )
        if color.isValid():
            new_hex = color.name()
            dr.set_color(new_hex)
            # Met à jour tous les rects du même groupe
            if dr.dc_key is not None and dr.dc_key in self.pick_rects:
                for other in self.pick_rects[dr.dc_key]:
                    other.set_color(new_hex)
                if self.on_color_changed_cb:
                    self.on_color_changed_cb(dr.dc_key, new_hex)
            self.draw()

    def _on_motion(self, event):
        if event.inaxes != self.ax or event.xdata is None:
            if self._vline is not None:
                self._vline.set_visible(False)
                self.draw_idle()
            return

        if self._active:
            self._active.on_motion(event.xdata)
            self.draw()
            return

        # Croix locale
        if self._vline is not None:
            ylim = self.ax.get_ylim()
            self._vline.set_data([event.xdata, event.xdata],
                                  [ylim[0], ylim[1]])
            self._vline.set_visible(True)
            self.draw_idle()

        if self.on_crosshair_move_cb:
            self.on_crosshair_move_cb(event.xdata)

        # Curseur
        from matplotlib.backend_bases import cursors
        cursor = cursors.POINTER
        for dr in reversed(self._all_rects()):
            c = dr.get_cursor(event.xdata, event.ydata)
            if c == "resize_horizontal":
                cursor = cursors.RESIZE_HORIZONTAL
                break
        try:
            self.figure.canvas.set_cursor(cursor)
        except Exception:
            pass

    def _on_release(self, event):
        if self._active:
            self._active.on_release()
            self._active = None
            if self._selector:
                self._selector.set_active(True)

    def _on_scroll(self, event):
        if event.inaxes != self.ax:
            return
        # Molette haut = pics plus grands (y_max diminue)
        # y_min TOUJOURS ancré à 0 — baseline fixe, pas d'intensités négatives
        factor   = 0.8 if event.button == "up" else 1.25
        _, y_max = self.ax.get_ylim()
        new_ymax = y_max * factor
        if new_ymax > 1:   # plancher minimal pour éviter l'inversion
            self.ax.set_ylim(0.0, new_ymax)
            self.draw()