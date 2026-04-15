import matplotlib.pyplot as plt
import matplotlib.widgets as widgets
import matplotlib.patches as patches
import numpy as np
from collections import defaultdict


# ---------------------------------------------------------------------------
# Détection du multiplet
# ---------------------------------------------------------------------------

def find_multiplet_boundaries(ppm: np.ndarray, intensites: np.ndarray,
                               dH: float, seuil_relatif: float = 0.015,
                               marge_ppm: float = 0.008) -> tuple:
    """
    Détecte les bords du multiplet autour de dH.
    Retourne (centre_ppm, demi_largeur, intensite_max)
    """
    seuil_bruit = np.max(np.abs(intensites)) * seuil_relatif

    fenetre    = 80
    idx_centre = np.argmin(np.abs(ppm - dH))
    idx_debut  = max(0, idx_centre - fenetre)
    idx_fin    = min(len(intensites) - 1, idx_centre + fenetre)
    idx_max    = idx_debut + np.argmax(np.abs(intensites[idx_debut:idx_fin + 1]))
    int_max    = intensites[idx_max]

    idx_g = idx_max
    while idx_g > 0 and np.abs(intensites[idx_g]) > seuil_bruit:
        idx_g -= 1

    idx_d = idx_max
    while idx_d < len(intensites) - 1 and np.abs(intensites[idx_d]) > seuil_bruit:
        idx_d += 1

    ppm_g = ppm[idx_g] + marge_ppm
    ppm_d = ppm[idx_d] - marge_ppm

    centre = dH
    demi   = max(abs(centre - ppm_g), abs(centre - ppm_d))
    if demi < 0.015:
        demi = 0.015

    return centre, demi, int_max


# ---------------------------------------------------------------------------
# Rectangle interactif à centre fixe
# ---------------------------------------------------------------------------

class DraggableRect:
    """
    Centre fixe = δH exact.
    Bord gauche (ppm élevé) et bord droit (ppm faible) sont indépendants.
    La zone de détection de bord est exprimée en unités DATA (ppm).
    """

    ALPHA = 0.45

    def __init__(self, ax, centre, demi_largeur, height, couleur,
                 couleur_droite=None):
        self.ax             = ax
        self.centre         = centre
        self.demi_g         = demi_largeur   # côté ppm élevé (gauche visuel)
        self.demi_d         = demi_largeur   # côté ppm faible (droite visuel)
        self.height         = height
        self.couleur        = couleur
        self.couleur_droite = couleur_droite

        self.y_rect  = 0 if height >= 0 else height
        self.hauteur = abs(height)

        self._mode       = None
        self._x_press    = None
        self._demi_press = None

        self._build_patches()

    # --- Propriétés calculées ---

    @property
    def x_left(self):
        """Bord gauche visuel = ppm le plus élevé."""
        return self.centre + self.demi_g

    @property
    def x_right(self):
        """Bord droit visuel = ppm le plus faible."""
        return self.centre - self.demi_d

    @property
    def width(self):
        return self.demi_g + self.demi_d

    def _edge_tol(self):
        """
        Tolérance en ppm pour détecter un bord.
        On utilise 15% de la demi-largeur, min 0.02 ppm.
        """
        return max((self.demi_g + self.demi_d) * 0.15, 0.02)

    # --- Construction des patches ---

    def _build_patches(self):
        xl = self.x_right   # x_left au sens matplotlib (valeur min)
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
                alpha=self.ALPHA, zorder=2
            )
            self.patch_half_r = patches.Rectangle(
                (xl + w / 2, self.y_rect), w / 2, self.hauteur,
                linewidth=0, facecolor=self.couleur_droite,
                alpha=self.ALPHA, zorder=2
            )
            self.patch_main = patches.Rectangle(
                (xl, self.y_rect), w, self.hauteur,
                linewidth=1.5, edgecolor="black",
                facecolor="none", zorder=3
            )
            self.ax.add_patch(self.patch_half_l)
            self.ax.add_patch(self.patch_half_r)
            self.ax.add_patch(self.patch_main)

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

    # --- Détection de zone ---

    def _detect_zone(self, x):
        """
        Retourne 'left', 'right', 'inside' ou None.
        L'axe est inversé : ppm élevé = gauche visuel.
        """
        tol = self._edge_tol()
        if abs(x - self.x_left) <= tol:    # bord gauche visuel (ppm élevé)
            return "left"
        if abs(x - self.x_right) <= tol:   # bord droit visuel (ppm faible)
            return "right"
        if self.x_right <= x <= self.x_left:
            return "inside"
        return None

    def contains(self, x, y):
        return (self.x_right <= x <= self.x_left
                and self.y_rect <= y <= self.y_rect + self.hauteur)

    # --- Événements ---

    def on_press(self, x, y):
        if not self.contains(x, y):
            return False
        zone = self._detect_zone(x)
        if zone in ("left", "right"):
            self._mode       = zone
            self._x_press    = x
            self._demi_press = self.demi_g if zone == "left" else self.demi_d
            return True
        return False   # clic au centre : on ne capture pas

    def on_motion(self, x):
        if self._mode is None:
            return
        dx = x - self._x_press

        if self._mode == "left":
            # Étirer le bord gauche visuel (ppm élevé)
            # dx > 0 → ppm augmente → bord gauche s'éloigne du centre
            new_demi = max(0.01, self._demi_press + dx)
            self.demi_g = new_demi

        elif self._mode == "right":
            # Étirer le bord droit visuel (ppm faible)
            # dx < 0 → ppm diminue → bord droit s'éloigne du centre
            new_demi = max(0.01, self._demi_press - dx)
            self.demi_d = new_demi

        self._update()

    def on_release(self):
        self._mode = None

    def get_cursor(self, x, y):
        """Retourne le nom du curseur matplotlib selon la position."""
        if not self.contains(x, y):
            return None
        zone = self._detect_zone(x)
        if zone in ("left", "right"):
            return "resize_horizontal"
        return "arrow"


# ---------------------------------------------------------------------------
# Affichage principal
# ---------------------------------------------------------------------------

def display_proton_spectrum(ppm: np.ndarray, intensites: np.ndarray,
                             groupes: dict = None, couleurs: dict = None):

    fig, ax = plt.subplots(figsize=(14, 4))
    plt.subplots_adjust(bottom=0.2)

    ax.plot(ppm, intensites, color="black", linewidth=0.8, zorder=3)
    ax.invert_xaxis()
    ax.set_xlabel("δ ¹H (ppm)")
    ax.set_ylabel("Intensité")
    ax.set_title("Spectre ¹H")

    x_min, x_max = ppm.min(), ppm.max()
    y_max_init   = intensites.max() * 1.2
    y_min_init   = -y_max_init * 0.3

    ax.set_xlim(x_max, x_min)
    ax.set_ylim(y_min_init, y_max_init)

    # --- Construction des rectangles ---
    rects = []

    if groupes and couleurs:

        dH_to_groups = defaultdict(list)
        for gid, info in groupes.items():
            for dH in info["protons"]:
                dH_to_groups[round(dH, 4)].append(gid)

        deja_traites = set()

        for gid, info in groupes.items():
            couleur = couleurs[gid]
            for dH in info["protons"]:
                dH_key   = round(dH, 4)
                partages = dH_to_groups[dH_key]

                if len(partages) == 2 and dH_key in deja_traites:
                    continue

                centre, demi, int_max = find_multiplet_boundaries(
                    ppm, intensites, dH
                )

                if len(partages) == 1:
                    dr = DraggableRect(ax, centre, demi, int_max, couleur)
                else:
                    deja_traites.add(dH_key)
                    couleur_d = couleurs[partages[1]]
                    dr = DraggableRect(ax, centre, demi, int_max,
                                       couleur, couleur_droite=couleur_d)
                rects.append(dr)

    # --- Événements souris ---
    state = {"active": None}

    def on_press(event):
        if event.inaxes != ax or event.xdata is None:
            return
        for dr in reversed(rects):
            if dr.on_press(event.xdata, event.ydata):
                state["active"] = dr
                break

    def on_motion(event):
        if event.inaxes != ax or event.xdata is None:
            return

        # Redimensionnement actif
        if state["active"]:
            state["active"].on_motion(event.xdata)
            fig.canvas.draw_idle()
            return

        # Changement de curseur selon position
        cursor = "arrow"
        for dr in reversed(rects):
            c = dr.get_cursor(event.xdata, event.ydata)
            if c is not None:
                cursor = c
                break
        try:
            fig.canvas.set_cursor(
                matplotlib_cursor(cursor)
            )
        except Exception:
            pass

    def on_release(event):
        if state["active"]:
            state["active"].on_release()
            state["active"] = None

    def on_scroll(event):
        if event.inaxes != ax:
            return
        factor = 0.85 if event.button == "up" else 1.15
        y_min, y_max = ax.get_ylim()
        ax.set_ylim(y_min * factor, y_max * factor)
        fig.canvas.draw_idle()

    # --- Boutons ---
    def zoom_to_peaks(event):
        seuil   = np.max(np.abs(intensites)) * 0.01
        indices = np.where(np.abs(intensites) > seuil)[0]
        if len(indices) == 0:
            return
        ppm_min = ppm[indices].min()
        ppm_max = ppm[indices].max()
        marge   = (ppm_max - ppm_min) * 0.05
        ax.set_xlim(ppm_max + marge, ppm_min - marge)
        fig.canvas.draw_idle()

    def reset_view(event):
        ax.set_xlim(x_max, x_min)
        ax.set_ylim(y_min_init, y_max_init)
        fig.canvas.draw_idle()

    ax_btn_zoom  = plt.axes([0.70, 0.05, 0.12, 0.06])
    ax_btn_reset = plt.axes([0.84, 0.05, 0.12, 0.06])
    btn_zoom     = widgets.Button(ax_btn_zoom,  "Ajuster aux pics")
    btn_reset    = widgets.Button(ax_btn_reset, "Vue complète")
    btn_zoom.on_clicked(zoom_to_peaks)
    btn_reset.on_clicked(reset_view)

    fig.canvas.mpl_connect("button_press_event",   on_press)
    fig.canvas.mpl_connect("motion_notify_event",  on_motion)
    fig.canvas.mpl_connect("button_release_event", on_release)
    fig.canvas.mpl_connect("scroll_event",         on_scroll)

    fig.text(
        0.01, 0.01,
        "Survol du bord ⟷ : redimensionner  |  Molette : intensité",
        fontsize=7, color="gray"
    )

    plt.show()


def matplotlib_cursor(name: str):
    """Convertit un nom lisible en constante curseur matplotlib."""
    from matplotlib.backend_bases import cursors
    mapping = {
        "arrow":              cursors.POINTER,
        "resize_horizontal":  cursors.RESIZE_HORIZONTAL,
        "fleur":              cursors.MOVE,
    }
    return mapping.get(name, cursors.POINTER)