import numpy as np
from scipy.ndimage import maximum_filter
import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import RectangleSelector
import matplotlib.gridspec as gridspec

_GS_LEFT         = 0.04
_GS_RIGHT        = 0.98
_GS_WIDTH_RATIOS = [1, 6]
_GS_WSPACE       = 0.02


class Spectrum2DCanvas(FigureCanvas):
    """
    Canvas HSQC avec :
    - Affichage des coordonnées ppm en temps réel (coin supérieur droit)
    - Clic droit -> snap au pic local le plus proche
    - Détection automatique des pics alignés (même δC) SANS tableau de picks
    - Fallback sur le DataFrame si disponible
    """

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(7, 6))
        super().__init__(self.fig)
        self.setParent(parent)

        self._ppm_f2       = None
        self._ppm_f1       = None
        self._data         = None
        self._nlevels      = 12
        self._seuil_factor = 0.05
        self._contour_pos  = None
        self._contour_neg  = None

        self._ppm_13c = None
        self._int_13c = None

        # Pics détectés automatiquement depuis le signal 2D
        self._auto_peaks   = None   # array (N,2) : colonnes [dH, dC]

        # DataFrame optionnel (si tableau HSQC fourni)
        self._df_peaks    = None
        self._tolerance   = 0.5
        self.single_pick_mode = False  # si True: pas de groupement CH2

        # Marqueurs sélectionnés
        self._markers = {}

        # Texte coordonnées
        self._coord_text = None

        self._zoom_stack = []
        self._selector   = None
        self._syncing    = False
        self._xlim_cid   = None

        # Croix
        self._vline_2d = None
        self._hline_2d = None
        self._vline_c  = None

        # Callbacks
        self.on_xlim_changed_cb   = None
        self.on_crosshair_move_cb = None
        self.on_peak_picked_cb    = None
        self.on_peak_add_to_group_cb = None  # (dc_key, dH_list, dc_val) mode pic seul

        self._build_axes()
        self._draw_empty()

        self.mpl_connect("scroll_event",        self._on_scroll)
        self.mpl_connect("motion_notify_event", self._on_motion)
        self.mpl_connect("figure_leave_event",  self._on_leave)
        self.mpl_connect("button_press_event",  self._on_press)

    # -------------------------------------------------------------------
    # Axes
    # -------------------------------------------------------------------

    def _build_axes(self):
        gs = gridspec.GridSpec(
            1, 2,
            figure=self.fig,
            width_ratios=_GS_WIDTH_RATIOS,
            wspace=_GS_WSPACE,
            left=_GS_LEFT, right=_GS_RIGHT,
            top=0.95, bottom=0.08
        )
        self.ax_2d = self.fig.add_subplot(gs[0, 1])
        self.ax_c  = self.fig.add_subplot(gs[0, 0], sharey=self.ax_2d)

        for lbl in self.ax_c.get_yticklabels():
            lbl.set_visible(False)

        self.ax_2d.set_xlabel("δ ¹H (ppm)", fontsize=8)
        self.ax_2d.set_ylabel("δ ¹³C (ppm)", fontsize=8)
        self.ax_2d.tick_params(labelsize=7)
        self.ax_c.tick_params(labelsize=7)

        for spine in ["top", "right", "bottom"]:
            self.ax_c.spines[spine].set_visible(False)
        self.ax_c.xaxis.set_visible(False)

        self._connect_xlim_cb()

    def _connect_xlim_cb(self):
        if self._xlim_cid is not None:
            try:
                self.ax_2d.callbacks.disconnect(self._xlim_cid)
            except Exception:
                pass
        self._xlim_cid = self.ax_2d.callbacks.connect(
            "xlim_changed", self._emit_xlim
        )

    # -------------------------------------------------------------------
    # Texte coordonnées
    # -------------------------------------------------------------------

    def _init_coord_text(self):
        """Crée le texte de coordonnées dans le coin supérieur droit."""
        self._coord_text = self.ax_2d.text(
            0.99, 0.97, "",
            transform=self.ax_2d.transAxes,
            ha="right", va="top",
            fontsize=7, color="dimgray",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                      alpha=0.7, edgecolor="lightgray"),
            zorder=20
        )

    def _update_coord_text(self, x_ppm, y_ppm):
        if self._coord_text is None:
            return
        if x_ppm is not None and y_ppm is not None:
            self._coord_text.set_text(
                f"¹H : {x_ppm:.3f} ppm\n¹³C : {y_ppm:.2f} ppm"
            )
        else:
            self._coord_text.set_text("")

    # -------------------------------------------------------------------
    # Vide
    # -------------------------------------------------------------------

    def _draw_empty(self):
        self.ax_2d.set_facecolor("#f8f8f8")
        self.ax_2d.text(
            0.5, 0.5,
            "Sélectionner une expérience 2D et cliquer Afficher",
            transform=self.ax_2d.transAxes,
            ha="center", va="center", fontsize=9, color="gray"
        )
        self.draw()

    # -------------------------------------------------------------------
    # Détection automatique des pics depuis les données 2D
    # -------------------------------------------------------------------

    def _detect_peaks_2d(self):
        """
        Détecte les maxima locaux dans le spectre 2D.
        Retourne un array (N, 2) avec colonnes [dH, dC].
        Utilise un filtre de maximum sur une fenêtre glissante.
        """
        if self._data is None:
            return None

        data_abs = np.abs(self._data)
        seuil    = np.max(data_abs) * self._seuil_factor

        # Fenêtre de 5x5 pixels pour le maximum local
        size    = 5
        max_img = maximum_filter(data_abs, size=size)
        mask    = (data_abs == max_img) & (data_abs > seuil)

        # Indices des maxima
        rows, cols = np.where(mask)

        if len(rows) == 0:
            return None

        # Convertit en ppm
        dC_vals = self._ppm_f1[rows]
        dH_vals = self._ppm_f2[cols]

        return np.column_stack([dH_vals, dC_vals])

    def _snap_to_nearest_auto(self, x_click, y_click):
        """
        Snap au pic le plus proche dans les pics détectés automatiquement.
        Retourne (dH, dC) du pic le plus proche ou None.
        """
        if self._auto_peaks is None or len(self._auto_peaks) == 0:
            return None

        dH_arr = self._auto_peaks[:, 0]
        dC_arr = self._auto_peaks[:, 1]

        # Normalise par plage visible pour équilibrer les deux axes
        xl = self.ax_2d.get_xlim()
        yl = self.ax_2d.get_ylim()
        range_dH = abs(xl[0] - xl[1]) or 1.0
        range_dC = abs(yl[0] - yl[1]) or 1.0

        dist = np.sqrt(
            ((dH_arr - x_click) / range_dH) ** 2 +
            ((dC_arr - y_click) / range_dC) ** 2
        )
        idx = np.argmin(dist)
        return float(dH_arr[idx]), float(dC_arr[idx])

    def _find_group_auto(self, dH_snap, dC_snap):
        """
        Trouve tous les pics au même δC (± tolérance).
        En mode single_pick_mode : retourne uniquement le pic cliqué.
        """
        dc_key = round(float(dC_snap), 4)

        if self.single_pick_mode:
            return dc_key, [float(dH_snap)]

        if self._auto_peaks is None:
            return dc_key, [dH_snap]

        dC_arr  = self._auto_peaks[:, 1]
        dH_arr  = self._auto_peaks[:, 0]
        mask    = np.abs(dC_arr - dC_snap) <= self._tolerance
        dH_list = dH_arr[mask].tolist()

        if not dH_list:
            dH_list = [dH_snap]

        return dc_key, dH_list

    # -------------------------------------------------------------------
    # DataFrame optionnel (si tableau HSQC fourni)
    # -------------------------------------------------------------------

    def set_peaks(self, df, tolerance: float = 0.5):
        self._df_peaks  = df
        self._tolerance = tolerance

    def _snap_to_nearest_df(self, x_click, y_click):
        if self._df_peaks is None or self._df_peaks.empty:
            return None
        range_dH = float(self._df_peaks["dH"].max() - self._df_peaks["dH"].min()) or 1.0
        range_dC = float(self._df_peaks["dC"].max() - self._df_peaks["dC"].min()) or 1.0
        dist = np.sqrt(
            ((self._df_peaks["dH"] - x_click) / range_dH) ** 2 +
            ((self._df_peaks["dC"] - y_click) / range_dC) ** 2
        )
        idx = dist.idxmin()
        return self._df_peaks.loc[idx]

    def _find_group_df(self, peak_row):
        dc     = peak_row["dC"]
        dc_key = round(float(dc), 4)
        if self.single_pick_mode:
            return dc_key, [float(peak_row["dH"])]
        mask   = (self._df_peaks["dC"] - dc).abs() <= self._tolerance
        return dc_key, self._df_peaks[mask]["dH"].tolist()

    # -------------------------------------------------------------------
    # Marqueurs
    # -------------------------------------------------------------------

    def add_marker(self, dc_key, dH_list, dc_val, couleur):
        if dc_key in self._markers:
            try:
                self._markers[dc_key].remove()
            except Exception:
                pass
        scatter = self.ax_2d.scatter(
            dH_list, [dc_val] * len(dH_list),
            s=60, facecolors="none",
            edgecolors=couleur, linewidths=1.5,
            zorder=5
        )
        self._markers[dc_key] = scatter
        self.draw_idle()

    def remove_marker(self, dc_key):
        if dc_key in self._markers:
            try:
                self._markers[dc_key].remove()
            except Exception:
                pass
            del self._markers[dc_key]
            self.draw_idle()

    def update_marker_color(self, dc_key, couleur):
        if dc_key in self._markers:
            self._markers[dc_key].set_edgecolors(couleur)
            self.draw_idle()

    def clear_markers(self):
        for dc_key in list(self._markers.keys()):
            self.remove_marker(dc_key)

    def auto_pick_all_peaks(self, already_picked=None):
        """
        Détecte automatiquement tous les pics locaux du spectre 2D courant
        et les ajoute au tableau de picking.
        already_picked : set ou list de dc_keys déjà pickés (pour éviter les doublons)
        """
        if self._data is None:
            return 0

        if already_picked is None:
            already_picked = set()
        else:
            already_picked = set(already_picked)

        # Détecte les pics
        peaks = self._detect_peaks_2d()
        if peaks is None or len(peaks) == 0:
            return 0

        # Groupe les pics par δC (avec tolérance)
        groups = {}
        for dH, dC in peaks:
            dc_key = round(float(dC), 4)

            # Cherche si ce groupe existe déjà
            found = False
            for existing_key in groups:
                if abs(existing_key - dc_key) <= self._tolerance:
                    groups[existing_key].append(float(dH))
                    found = True
                    break

            if not found:
                groups[dc_key] = [float(dH)]

        # Dispatch chaque groupe (en ignorant les doublons)
        num_picked = 0
        for dc_key, dH_list in groups.items():
            # Saute si ce groupe est déjà pick
            if dc_key in already_picked:
                continue
            # Utilise la moyenne des dH comme dc_val
            dC_val = float(dc_key)
            self._dispatch_pick(dc_key, dH_list, dC_val)
            num_picked += 1

        return num_picked

    # -------------------------------------------------------------------
    # Tracé principal
    # -------------------------------------------------------------------

    def plot(self, ppm_f2, ppm_f1, data, title="",
             ppm_13c=None, int_13c=None):
        self._ppm_f2       = ppm_f2
        self._ppm_f1       = ppm_f1
        self._data         = data
        self._seuil_factor = 0.05
        self._contour_pos  = None
        self._contour_neg  = None
        self._zoom_stack   = []
        self._markers      = {}
        self._ppm_13c      = ppm_13c
        self._int_13c      = int_13c

        self.ax_2d.cla()
        self.ax_c.cla()
        self._connect_xlim_cb()

        for spine in ["top", "right", "bottom"]:
            self.ax_c.spines[spine].set_visible(False)
        self.ax_c.xaxis.set_visible(False)
        for lbl in self.ax_c.get_yticklabels():
            lbl.set_visible(False)

        self._redraw_contours(init=True)
        self.ax_2d.invert_xaxis()
        self.ax_2d.invert_yaxis()
        self.ax_2d.set_xlabel("δ ¹H (ppm)", fontsize=8)
        self.ax_2d.set_ylabel("δ ¹³C (ppm)", fontsize=8)
        self.ax_2d.set_title(title, fontsize=9)

        self._draw_13c()
        self._init_crosshair()
        self._init_coord_text()
        self._init_selector()

        # Détection automatique des pics
        self._auto_peaks = self._detect_peaks_2d()

        self.draw()

    def _draw_13c(self):
        if self._ppm_13c is not None and self._int_13c is not None:
            self.ax_c.plot(self._int_13c, self._ppm_13c,
                           color="black", linewidth=0.6)
            xmax = np.max(np.abs(self._int_13c)) * 1.2
            self.ax_c.set_xlim(xmax, -xmax * 0.05)
        else:
            self.ax_c.set_facecolor("#f8f8f8")
            self.ax_c.text(
                0.5, 0.5, "¹³C\nnon\nchargé",
                transform=self.ax_c.transAxes,
                ha="center", va="center", fontsize=7, color="gray"
            )

    # -------------------------------------------------------------------
    # Contours
    # -------------------------------------------------------------------

    def _redraw_contours(self, init=False):
        if self._data is None:
            return
        if not init:
            xlim = self.ax_2d.get_xlim()
            ylim = self.ax_2d.get_ylim()

        for attr in ("_contour_pos", "_contour_neg"):
            c = getattr(self, attr)
            if c is not None:
                try:
                    c.remove()
                except Exception:
                    pass
            setattr(self, attr, None)

        vmax    = np.max(np.abs(self._data))
        seuil   = vmax * self._seuil_factor
        if seuil <= 0:
            return
        niveaux = np.geomspace(seuil, vmax * 0.95, num=self._nlevels)

        try:
            self._contour_pos = self.ax_2d.contour(
                self._ppm_f2, self._ppm_f1, self._data,
                levels=niveaux, colors="black", linewidths=0.5
            )
        except Exception:
            self._contour_pos = None

        try:
            self._contour_neg = self.ax_2d.contour(
                self._ppm_f2, self._ppm_f1, self._data,
                levels=-niveaux[::-1], colors="#cc0000", linewidths=0.5
            )
        except Exception:
            self._contour_neg = None

        if not init:
            self.ax_2d.set_xlim(xlim)
            self.ax_2d.set_ylim(ylim)

        # Remet les lignes de croix au premier plan
        if not init and self._vline_2d is not None:
            try:
                self.ax_2d.add_line(self._vline_2d)
                self.ax_2d.add_line(self._hline_2d)
            except Exception:
                pass

    # -------------------------------------------------------------------
    # Croix
    # -------------------------------------------------------------------

    def _init_crosshair(self):
        kw = dict(color="gray", linewidth=0.7, linestyle="--",
                  zorder=10, visible=False)
        self._vline_2d, = self.ax_2d.plot([], [], **kw)
        self._hline_2d, = self.ax_2d.plot([], [], **kw)
        self._vline_c,  = self.ax_c.plot([], [], **kw)

    def _update_crosshair(self, x_ppm, y_ppm):
        if self._vline_2d is None:
            return
        xl = self.ax_2d.get_xlim()
        yl = self.ax_2d.get_ylim()
        if x_ppm is not None and y_ppm is not None:
            self._vline_2d.set_data([x_ppm, x_ppm], [yl[0], yl[1]])
            self._hline_2d.set_data([xl[0], xl[1]], [y_ppm, y_ppm])
            self._vline_2d.set_visible(True)
            self._hline_2d.set_visible(True)
        else:
            self._vline_2d.set_visible(False)
            self._hline_2d.set_visible(False)
        if self._vline_c is not None:
            xcl = self.ax_c.get_xlim()
            if y_ppm is not None:
                self._vline_c.set_data([xcl[0], xcl[1]], [y_ppm, y_ppm])
                self._vline_c.set_visible(True)
            else:
                self._vline_c.set_visible(False)
        self._update_coord_text(x_ppm, y_ppm)
        self.draw_idle()

    def update_crosshair_from_1d(self, x_ppm):
        if self._vline_2d is None:
            return
        yl = self.ax_2d.get_ylim()
        if x_ppm is not None:
            self._vline_2d.set_data([x_ppm, x_ppm], [yl[0], yl[1]])
            self._vline_2d.set_visible(True)
        else:
            self._vline_2d.set_visible(False)
        self._hline_2d.set_visible(False)
        if self._vline_c is not None:
            self._vline_c.set_visible(False)
        self.draw_idle()

    # -------------------------------------------------------------------
    # Zoom
    # -------------------------------------------------------------------

    def _init_selector(self):
        if self._selector:
            self._selector.set_active(False)
        self._selector = RectangleSelector(
            self.ax_2d, self._on_zoom_select,
            useblit=True, button=[1],
            minspanx=5, minspany=5,
            spancoords="pixels", interactive=False,
            props=dict(facecolor="lightblue", alpha=0.25,
                       edgecolor="steelblue", linewidth=1)
        )

    def _on_zoom_select(self, eclick, erelease):
        x1, x2 = eclick.xdata, erelease.xdata
        y1, y2 = eclick.ydata, erelease.ydata
        if None in (x1, x2, y1, y2):
            return
        if abs(x1 - x2) < 0.001 or abs(y1 - y2) < 0.001:
            return
        self._zoom_stack.append(
            (self.ax_2d.get_xlim(), self.ax_2d.get_ylim())
        )
        self.ax_2d.set_xlim(max(x1, x2), min(x1, x2))
        self.ax_2d.set_ylim(min(y1, y2), max(y1, y2))
        # Recalcule les pics sur la zone visible
        self._auto_peaks = self._detect_peaks_2d()
        self.draw()

    def dezoom(self):
        if self._zoom_stack:
            xlim, ylim = self._zoom_stack.pop()
            self.ax_2d.set_xlim(xlim)
            self.ax_2d.set_ylim(ylim)
        else:
            self.reset_view()
        self.draw()

    def reset_view(self):
        if self._ppm_f2 is None:
            return
        self._zoom_stack = []
        self.ax_2d.set_xlim(self._ppm_f2.max(), self._ppm_f2.min())
        self.ax_2d.set_ylim(self._ppm_f1.max(), self._ppm_f1.min())
        self._auto_peaks = self._detect_peaks_2d()
        self.draw()

    def reset_view_no_sync(self):
        """Reset 2D view without triggering synchronization with 1D spectrum."""
        if self._ppm_f2 is None:
            return
        self._zoom_stack = []
        self._syncing = True  # Prevent xlim change from syncing back to 1D
        self.ax_2d.set_xlim(self._ppm_f2.max(), self._ppm_f2.min())
        self.ax_2d.set_ylim(self._ppm_f1.max(), self._ppm_f1.min())
        self._auto_peaks = self._detect_peaks_2d()
        self.draw()
        self._syncing = False  # Re-enable synchronization for future zooms

    # -------------------------------------------------------------------
    # Synchro
    # -------------------------------------------------------------------

    def _emit_xlim(self, ax):
        if self._syncing:
            return
        if self.on_xlim_changed_cb:
            self.on_xlim_changed_cb(ax.get_xlim())

    def sync_xlim(self, xlim):
        if self._syncing or self._ppm_f2 is None:
            return
        self._syncing = True
        self.ax_2d.set_xlim(xlim)
        
        # Find peaks within the zoomed horizontal range and zoom 2D to show them
        if self._auto_peaks is not None and len(self._auto_peaks) > 0:
            # Extract horizontal (dH) coordinates of peaks
            dH_arr = self._auto_peaks[:, 0]
            dC_arr = self._auto_peaks[:, 1]
            
            # Find peaks within the xlim range (account for inverted axis)
            xlim_min, xlim_max = min(xlim), max(xlim)
            mask = (dH_arr >= xlim_min) & (dH_arr <= xlim_max)
            
            if np.any(mask):
                # Get dC values of peaks in the zoomed region
                dC_in_range = dC_arr[mask]
                dC_min = dC_in_range.min()
                dC_max = dC_in_range.max()
                
                # Add margin (5% of range)
                dC_range = dC_max - dC_min
                margin = dC_range * 0.05 if dC_range > 0 else 0.5
                
                # Set ylim to show peaks with margin
                new_ylim = (dC_max + margin, dC_min - margin)
                self.ax_2d.set_ylim(new_ylim)
            else:
                # Fallback: if no peaks found, use proportional zoom
                current_ylim = self.ax_2d.get_ylim()
                y_center = (current_ylim[0] + current_ylim[1]) / 2
                full_y_range = self._ppm_f1.max() - self._ppm_f1.min()
                full_x_range = self._ppm_f2.max() - self._ppm_f2.min()
                new_x_range = abs(xlim[1] - xlim[0])
                zoom_factor = new_x_range / full_x_range if full_x_range > 0 else 1.0
                new_y_range = full_y_range * zoom_factor
                y_half_range = new_y_range / 2
                new_ylim = (y_center + y_half_range, y_center - y_half_range)
                y_min = self._ppm_f1.min()
                y_max = self._ppm_f1.max()
                new_ylim = (min(new_ylim[0], y_max), max(new_ylim[1], y_min))
                self.ax_2d.set_ylim(new_ylim)
        
        self.draw()
        self._syncing = False

    # -------------------------------------------------------------------
    # Événements souris
    # -------------------------------------------------------------------

    def _on_press(self, event):
        if event.button != 3 or event.inaxes != self.ax_2d:
            return
        if event.xdata is None or event.ydata is None:
            return

        # Priorité au DataFrame si disponible
        if self._df_peaks is not None:
            row = self._snap_to_nearest_df(event.xdata, event.ydata)
            if row is not None:
                dc_key, dH_list = self._find_group_df(row)
                self._dispatch_pick(dc_key, dH_list, float(row["dC"]))
            return

        # Détection automatique sur le signal 2D
        result = self._snap_to_nearest_auto(event.xdata, event.ydata)
        if result is not None:
            dH_snap, dC_snap = result
            dc_key, dH_list = self._find_group_auto(dH_snap, dC_snap)
            self._dispatch_pick(dc_key, dH_list, dC_snap)

    def _dispatch_pick(self, dc_key, dH_list, dc_val):
        """
        En mode single_pick_mode, utilise on_peak_add_to_group_cb qui permet
        d'ajouter un proton à un groupe existant ou de créer un nouveau groupe.
        En mode normal, utilise on_peak_picked_cb (groupement automatique).
        """
        if self.single_pick_mode and self.on_peak_add_to_group_cb is not None:
            self.on_peak_add_to_group_cb(dc_key, dH_list, dc_val)
        elif self.on_peak_picked_cb is not None:
            self.on_peak_picked_cb(dc_key, dH_list, dc_val)

    def _on_motion(self, event):
        if event.inaxes == self.ax_2d:
            self._update_crosshair(event.xdata, event.ydata)
            if self.on_crosshair_move_cb:
                self.on_crosshair_move_cb(event.xdata)
        elif event.inaxes == self.ax_c:
            self._update_crosshair(None, event.ydata)
        else:
            self._update_crosshair(None, None)

    def _on_leave(self, event):
        self._update_crosshair(None, None)
        if self.on_crosshair_move_cb:
            self.on_crosshair_move_cb(None)

    def _on_scroll(self, event):
        if event.inaxes is None:
            return

        if event.inaxes == self.ax_2d and self._data is not None:
            factor = 0.77 if event.button == "up" else 1.3
            self._seuil_factor = float(np.clip(
                self._seuil_factor * factor, 0.001, 0.5
            ))
            self._redraw_contours(init=False)
            # Recalcule les pics auto avec le nouveau seuil
            self._auto_peaks = self._detect_peaks_2d()
            self.draw()
            return

        if event.inaxes == self.ax_c and self._int_13c is not None:
            factor = 0.8 if event.button == "up" else 1.25
            x_min, x_max = self.ax_c.get_xlim()
            self.ax_c.set_xlim(x_min * factor, x_max)
            self.draw()
            return