import os, json
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QLineEdit, QTextEdit, QListWidget, QFileDialog, QDoubleSpinBox,
    QSplitter, QGroupBox, QComboBox, QTabWidget, QCheckBox,
    QDialog, QRadioButton, QButtonGroup
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from src.loader import scan_experiment_folder, load_proton_spectrum, load_2d_spectrum
from src.parser import parse_hsqc_table
from src.grouper import group_by_carbon
from src.colorizer import assign_colors
from src.gui.spectrum_canvas import SpectrumCanvas
from src.gui.spectrum2d_canvas import Spectrum2DCanvas
from src.gui.color_manager import ColorManager
from src.gui.peaks_table import PeaksTable
from src.gui.molecule_canvas import MoleculeCanvas
from src.gui.report_window import ReportWindow

HISTORY_FILE  = "path_history.json"
MAX_HISTORY   = 10
MOBILE_PREFIX = "mobile_"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NMR Colorizer")
        self.setMinimumSize(1300, 900)
        self._experiences = []
        self._ppm = self._intensites = self._ppm_13c = self._int_13c = None
        self._groupes = self._couleurs = None
        self._history       = self._load_history()
        self._color_manager = ColorManager()
        self._pending_atom_idx = None
        self._attributions     = {}
        self._build_ui()
        self._wire_sync()

    def _load_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                return json.load(open(HISTORY_FILE))
        except Exception: pass
        return []

    def _save_history(self):
        try: json.dump(self._history, open(HISTORY_FILE, "w"))
        except Exception: pass

    def _add_to_history(self, path):
        if path in self._history: self._history.remove(path)
        self._history = [path] + self._history[:MAX_HISTORY-1]
        self._save_history(); self._refresh_history_combo()

    def _refresh_history_combo(self):
        self.combo_history.blockSignals(True)
        self.combo_history.clear()
        self.combo_history.addItem("Historique...")
        for p in self._history: self.combo_history.addItem(p)
        self.combo_history.blockSignals(False)

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        h_split = QSplitter(Qt.Horizontal)
        h_split.addWidget(self._build_left_panel())
        h_split.addWidget(self._build_right_panel())
        h_split.setSizes([320, 980]); h_split.setChildrenCollapsible(False)
        root = QHBoxLayout(central); root.setContentsMargins(8,8,8,8)
        root.addWidget(h_split)

    def _build_left_panel(self):
        panel = QWidget(); layout = QVBoxLayout(panel)
        layout.setSpacing(6); layout.setAlignment(Qt.AlignTop)

        # Dossier Bruker
        grp = QGroupBox("Dossier Bruker"); vf = QVBoxLayout(grp)
        self.combo_history = QComboBox(); self._refresh_history_combo()
        self.combo_history.activated.connect(self._on_history_selected)
        vf.addWidget(self.combo_history)
        row = QHBoxLayout(); self.edit_path = QLineEdit()
        self.edit_path.setPlaceholderText("Chemin du dossier essai...")
        btn = QPushButton("..."); btn.setFixedWidth(30); btn.clicked.connect(self._browse_folder)
        row.addWidget(self.edit_path); row.addWidget(btn); vf.addLayout(row)
        b = QPushButton("Scanner les expériences"); b.clicked.connect(self._scan_folder); vf.addWidget(b)
        lbl = QLabel("Expériences :"); lbl.setFont(QFont("Arial",8)); vf.addWidget(lbl)
        self.list_exp = QListWidget(); self.list_exp.setMaximumHeight(110)
        self.list_exp.itemClicked.connect(self._select_proton); vf.addWidget(self.list_exp)
        layout.addWidget(grp)

        # Nom du composé
        grp = QGroupBox("Composé"); vc = QVBoxLayout(grp)
        self.edit_compound = QLineEdit()
        self.edit_compound.setPlaceholderText("Nom du composé (ex: FLO000009AB)...")
        self.edit_compound.setFont(QFont("Arial", 9))
        vc.addWidget(self.edit_compound)
        layout.addWidget(grp)

        # Tolérance + mode pick (ultra-compact)
        row_params = QHBoxLayout()
        row_params.addWidget(QLabel("δC tol:"))
        self.spin_tol = QDoubleSpinBox(); self.spin_tol.setRange(0.01,5.0)
        self.spin_tol.setSingleStep(0.1); self.spin_tol.setValue(0.5)
        self.spin_tol.setFixedWidth(60); row_params.addWidget(self.spin_tol)
        row_params.addWidget(QLabel("ppm"))
        self.chk_single = QCheckBox("Pic seul")
        self.chk_single.setFont(QFont("Arial",8))
        self.chk_single.setToolTip("Désactive la détection CH₂/CH₃ automatique\nChaque clic = un seul proton")
        self.chk_single.toggled.connect(self._on_single_mode_toggled)
        row_params.addWidget(self.chk_single)
        row_params.addStretch()
        layout.addLayout(row_params)

        # Tableau HSQC
        grp = QGroupBox("Tableau HSQC"); vh = QVBoxLayout(grp); vh.setSpacing(3)
        # Barre titre avec bouton agrandir
        row_title = QHBoxLayout()
        lbl_hsqc = QLabel(""); lbl_hsqc.setFixedWidth(0)
        row_title.addStretch()
        btn_expand = QPushButton("⊞ Agrandir le tableau")
        btn_expand.setFixedHeight(20); btn_expand.setFont(QFont("Arial",7))
        btn_expand.clicked.connect(self._expand_peaks_table)
        row_title.addWidget(btn_expand)
        vh.addLayout(row_title)
        self.tab_hsqc = QTabWidget(); self.tab_hsqc.setFont(QFont("Arial",8))
        w = QWidget(); vt = QVBoxLayout(w); vt.setContentsMargins(0,4,0,0)
        self.text_hsqc = QTextEdit()
        self.text_hsqc.setPlaceholderText("Coller le tableau HSQC depuis TopSpin...")
        self.text_hsqc.setFont(QFont("Courier",8)); self.text_hsqc.setMinimumHeight(60)
        vt.addWidget(self.text_hsqc)
        b = QPushButton("Appliquer"); b.clicked.connect(self._display_1d); vt.addWidget(b)
        self.tab_hsqc.addTab(w, "Copier-coller")
        w2 = QWidget(); vk = QVBoxLayout(w2); vk.setContentsMargins(0,4,0,0)
        self.peaks_table = PeaksTable()
        self.peaks_table.table.setMinimumHeight(100)  # ~4 lignes
        self.peaks_table.table.setMaximumHeight(140)
        vk.addWidget(self.peaks_table)
        self.peaks_table.row_deleted.connect(self._on_table_row_deleted)
        self.peaks_table.row_edited.connect(self._on_table_row_edited)
        self.peaks_table.color_changed.connect(self._on_table_color_changed)
        self.peaks_table.row_added_manually.connect(self._on_table_row_added_manually)
        self.tab_hsqc.addTab(w2, "Picks éditables")
        vh.addWidget(self.tab_hsqc)
        layout.addWidget(grp, stretch=4)

        # Actions 1H
        grp = QGroupBox("Spectre ¹H"); va = QVBoxLayout(grp); va.setSpacing(3)
        for lbl, slot in [
            ("Afficher le spectre ¹H", self._display_1d),
            ("📊 Afficher 1D + 2D", self._display_both),
            ("Exporter PNG", self._export_png),
            ("📄 Ouvrir le rapport", self._open_report)]:
            b = QPushButton(lbl); b.setFixedHeight(22); b.clicked.connect(slot); va.addWidget(b)
        layout.addWidget(grp, stretch=1)

        # Spectre 2D
        grp = QGroupBox("Spectre 2D"); v2 = QVBoxLayout(grp); v2.setSpacing(3)
        row = QHBoxLayout(); self.combo_2d = QComboBox()
        self.combo_2d.setPlaceholderText("Expérience 2D...")
        row.addWidget(self.combo_2d)
        b = QPushButton("Afficher"); b.setFixedWidth(60); b.clicked.connect(self._display_2d); row.addWidget(b)
        v2.addLayout(row)
        row = QHBoxLayout(); self.combo_13c = QComboBox()
        self.combo_13c.setPlaceholderText("Expérience ¹³C...")
        row.addWidget(self.combo_13c)
        b = QPushButton("Charger"); b.setFixedWidth(60); b.clicked.connect(self._load_13c); row.addWidget(b)
        v2.addLayout(row)
        for lbl, slot in [("← Dézoom 2D", lambda: self.canvas_2d.dezoom()),
                           ("Vue complète 2D", lambda: self.canvas_2d.reset_view_no_sync()),
                           ("Auto-pick all peaks", self._auto_pick_all_peaks)]:
            b = QPushButton(lbl); b.setFixedHeight(22); b.clicked.connect(slot); v2.addWidget(b)
        layout.addWidget(grp, stretch=1)

        # Pick peaking & Attribution
        grp = QGroupBox("Pick peaking & Attribution"); vkk = QVBoxLayout(grp); vkk.setSpacing(3)
        lbl = QLabel("• Clic droit HSQC → groupe\n"
                     "• Clic droit ¹H → proton mobile (NH₂/OH)\n"
                     "• Double-clic rectangle → couleur\n"
                     "• Clic atome molécule + clic rectangle → attribution")
        lbl.setFont(QFont("Arial",7)); lbl.setWordWrap(True); vkk.addWidget(lbl)
        row = QHBoxLayout()
        b = QPushButton("↩ Annuler"); b.setFixedHeight(22); b.clicked.connect(self._undo_last_pick); row.addWidget(b)
        b = QPushButton("Effacer tout"); b.setFixedHeight(22); b.clicked.connect(self._clear_picks); row.addWidget(b)
        vkk.addLayout(row)
        row2 = QHBoxLayout()
        b = QPushButton("Importer .mol/.sdf"); b.setFixedHeight(22); b.clicked.connect(self._import_molecule); row2.addWidget(b)
        lbl_paste = QLabel("💡 Ctrl+V : coller depuis Biovia/ChemDraw")
        lbl_paste.setFont(QFont("Arial", 7)); lbl_paste.setStyleSheet("color:#666;"); lbl_paste.setWordWrap(True)
        vkk.addWidget(lbl_paste)
        b = QPushButton("Effacer attributions"); b.setFixedHeight(22); b.clicked.connect(self._clear_attributions); row2.addWidget(b)
        vkk.addLayout(row2)
        self.lbl_attr = QLabel(""); self.lbl_attr.setFont(QFont("Arial",7))
        self.lbl_attr.setStyleSheet("color:#005599;"); self.lbl_attr.setWordWrap(True)
        vkk.addWidget(self.lbl_attr)
        layout.addWidget(grp, stretch=1)

        self.lbl_status = QLabel("Prêt.")
        self.lbl_status.setFont(QFont("Arial",8)); self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)
        return panel

    def _build_right_panel(self):
        panel = QWidget(); layout = QVBoxLayout(panel)
        layout.setContentsMargins(0,0,0,0); layout.setSpacing(2)
        
        # Container with splitter and toolbar
        container = QWidget()
        container_layout = QVBoxLayout(container); container_layout.setContentsMargins(0,0,0,0); container_layout.setSpacing(0)
        
        # Top toolbar for zoom controls (positioned in upper right)
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar); toolbar_layout.setContentsMargins(4,4,4,2); toolbar_layout.setSpacing(2)
        toolbar_layout.addStretch()
        
        # Zoom buttons
        btn_zoom_to = QPushButton("Ajuster"); btn_zoom_to.setFixedSize(50, 26); btn_zoom_to.setFont(QFont("Arial",7)); btn_zoom_to.clicked.connect(lambda: self.canvas_1d.zoom_to_peaks()); toolbar_layout.addWidget(btn_zoom_to)
        btn_zoom_out = QPushButton("🔍"); btn_zoom_out.setFixedSize(28, 26); btn_zoom_out.setFont(QFont("Arial",9)); btn_zoom_out.clicked.connect(lambda: self.canvas_1d.dezoom()); toolbar_layout.addWidget(btn_zoom_out)
        btn_reset = QPushButton("⟲"); btn_reset.setFixedSize(28, 26); btn_reset.setFont(QFont("Arial",10)); btn_reset.clicked.connect(self._reset_all_views); toolbar_layout.addWidget(btn_reset)
        
        toolbar.setFixedHeight(32)
        container_layout.addWidget(toolbar)
        
        # Splitter with canvases
        v_split = QSplitter(Qt.Vertical)
        self.canvas_1d = SpectrumCanvas(); v_split.addWidget(self.canvas_1d)
        self.canvas_2d = Spectrum2DCanvas(); v_split.addWidget(self.canvas_2d)
        self.mol_canvas = MoleculeCanvas(); v_split.addWidget(self.mol_canvas)
        v_split.setSizes([200, 400, 200])
        container_layout.addWidget(v_split)
        layout.addWidget(container)
        return panel

    def _wire_sync(self):
        self.canvas_1d.on_xlim_changed_cb   = self.canvas_2d.sync_xlim
        self.canvas_2d.on_xlim_changed_cb   = self.canvas_1d.sync_xlim
        self.canvas_1d.on_crosshair_move_cb = self.canvas_2d.update_crosshair_from_1d
        self.canvas_2d.on_crosshair_move_cb = self.canvas_1d.update_crosshair
        self.canvas_2d.on_peak_picked_cb        = self._on_peak_picked
        self.canvas_2d.on_peak_add_to_group_cb  = self._on_peak_add_to_group
        self.canvas_1d.on_color_changed_cb  = self._on_color_changed_from_1d
        self.canvas_1d.on_rect_clicked_cb   = self._on_rect_clicked_for_attribution
        self.canvas_1d.on_mobile_proton_cb  = self._on_mobile_proton_picked
        self.mol_canvas.on_atom_clicked     = self._on_atom_clicked

    # --- Pick peaking ---
    def _on_peak_picked(self, dc_key, dH_list, dc_val):
        if self._ppm is None: self._status("Chargez d'abord le spectre ¹H."); return
        if dc_key in self._color_manager.all_groups(): return
        couleur = self._color_manager.add_group(dc_key, dH_list)
        self.canvas_1d.add_rect_group(dH_list, couleur, dc_key)
        self.canvas_2d.add_marker(dc_key, dH_list, dc_val, couleur)
        self.peaks_table.add_pick(dc_key, dH_list, dc_val, couleur)
        self.tab_hsqc.setCurrentIndex(1)
        n = len(dH_list)
        self._status(f"Groupe δC={dc_key} — CH{n if n>1 else ''} ({n} H)")

    def _on_peak_add_to_group(self, dc_key, dH_list, dc_val):
        """
        Mode pic seul : ajoute un proton à un groupe existant ou crée un nouveau.
        Appelé à chaque clic droit en mode single_pick_mode.
        """
        if self._ppm is None:
            return

        existing = self._color_manager.all_groups()
        dH = dH_list[0] if dH_list else None
        if dH is None:
            return

        if dc_key in existing:
            # Groupe existant → ajoute le proton
            couleur = self._color_manager.get_color(dc_key)
            self.canvas_1d.add_rect_group([dH], couleur, dc_key)
            # Met à jour le marqueur 2D avec les dH existants + le nouveau
            current_group = self._color_manager.all_groups().get(dc_key, {})
            all_dH = list(current_group.get("protons", [])) + [dH]
            self.canvas_2d.add_marker(dc_key, all_dH, dc_val, couleur)
            self.peaks_table.add_pick(dc_key, [dH], dc_val, couleur)
            self.tab_hsqc.setCurrentIndex(1)
            self._status(f"Proton ajouté au groupe δC={dc_key} : δH={dH:.4f}")
        else:
            # Nouveau groupe → cercle sur le 2D
            couleur = self._color_manager.add_group(dc_key, [dH])
            self.canvas_1d.add_rect_group([dH], couleur, dc_key)
            self.canvas_2d.add_marker(dc_key, [dH], dc_val, couleur)
            self.peaks_table.add_pick(dc_key, [dH], dc_val, couleur)
            self.tab_hsqc.setCurrentIndex(1)
            self._status(f"Nouveau groupe δC={dc_key} — δH={dH:.4f}")

    def _on_mobile_proton_picked(self, dH: float):
        if self._ppm is None: return
        dc_key = f"{MOBILE_PREFIX}{dH:.4f}"
        if dc_key in self._color_manager.all_groups(): return
        couleur = self._color_manager.add_group(dc_key, [dH])
        self.canvas_1d.add_rect_group([dH], couleur, dc_key)
        self.peaks_table.add_mobile_pick(dc_key, dH, couleur)
        self.tab_hsqc.setCurrentIndex(1)
        self._status(f"Proton mobile : δH={dH:.4f} ppm")

    # --- Attribution molécule ---
    def _on_atom_clicked(self, atom_idx: int):
        self._pending_atom_idx = atom_idx
        self.lbl_attr.setText(f"Atome #{atom_idx} → cliquez sur un rectangle ¹H")

    def _on_rect_clicked_for_attribution(self, dc_key):
        if self._pending_atom_idx is None: return
        atom_idx = self._pending_atom_idx
        couleur  = self._color_manager.get_color(dc_key)
        self.mol_canvas.assign_color(atom_idx, dc_key, couleur)
        self._attributions[atom_idx] = dc_key
        self.lbl_attr.setText(f"Atome #{atom_idx} → δC={dc_key} ✓")
        self._pending_atom_idx = None

    def _import_molecule(self):
        path, _ = QFileDialog.getOpenFileName(self,"Importer","","Molécules (*.mol *.sdf)")
        if not path: return
        ok = self.mol_canvas.load_molecule(path)
        if ok: self._attributions={}; self._status(f"Structure : {os.path.basename(path)}")
        else: self._status("Erreur : impossible de lire le fichier.")

    def _clear_attributions(self):
        self._attributions={}; self._pending_atom_idx=None
        self.mol_canvas.clear_attributions(); self.lbl_attr.setText("")

    # --- Couleurs ---
    def _on_color_changed_from_1d(self, dc_key, new_color):
        self._color_manager.set_color(dc_key, new_color)
        if not str(dc_key).startswith(MOBILE_PREFIX): self.canvas_2d.update_marker_color(dc_key, new_color)
        self.peaks_table.update_color(dc_key, new_color)
        self.mol_canvas.update_color_for_key(dc_key, new_color)

    def _undo_last_pick(self):
        dc_key = self._color_manager.remove_last()
        if dc_key is not None:
            self.canvas_1d.remove_rect_group(dc_key)
            if not str(dc_key).startswith(MOBILE_PREFIX): self.canvas_2d.remove_marker(dc_key)
            self.peaks_table.remove_pick(dc_key)

    def _auto_pick_all_peaks(self):
        """Détecte automatiquement tous les pics locaux du spectre 2D courant."""
        already_picked = self._color_manager.all_groups().keys()
        num_picked = self.canvas_2d.auto_pick_all_peaks(already_picked=already_picked)
        if num_picked and num_picked > 0:
            self._status(f"Auto-picking complété : {num_picked} nouveau(x) groupe(s).")
        else:
            self._status("Aucun nouveau pic détecté (tous déjà pickés).")

    def _clear_picks(self):
        self._color_manager.reset(); self.canvas_1d.clear_pick_rects()
        self.canvas_2d.clear_markers(); self.peaks_table.clear_all()

    # --- Tableau ---
    def _on_table_row_deleted(self, dc_key, dH):
        if dH is not None: self.canvas_1d.remove_single_rect(dc_key, dH)
        if not self.canvas_1d.pick_rects.get(dc_key):
            self._color_manager.remove_group_by_key(dc_key)
            if not str(dc_key).startswith(MOBILE_PREFIX): self.canvas_2d.remove_marker(dc_key)

    def _on_table_row_edited(self, dc_key_old, dH, dC):
        if self._ppm: self.canvas_1d.update_rect_position(dc_key_old, dH)

    def _on_table_color_changed(self, dc_key, color):
        self._color_manager.set_color(dc_key, color)
        self.canvas_1d.update_group_color(dc_key, color)
        if not str(dc_key).startswith(MOBILE_PREFIX): self.canvas_2d.update_marker_color(dc_key, color)
        self.mol_canvas.update_color_for_key(dc_key, color)

    def _on_table_row_added_manually(self, dH, dC):
        if self._ppm is None: return
        dc_key = round(dC,4); couleur = self._color_manager.add_group(dc_key, [dH])
        self.canvas_1d.add_rect_group([dH], couleur, dc_key)
        self.peaks_table.update_color(dc_key, couleur)

    # --- Navigation ---
    def _reset_all_views(self):
        """Reset both 1D and 2D spectrum views to full extent."""
        self.canvas_1d.reset_view()
        self.canvas_2d.reset_view()

    def _on_history_selected(self, idx):
        if idx==0: return
        self.edit_path.setText(self._history[idx-1]); self._scan_folder()

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self,"Sélectionner le dossier essai")
        if path: self.edit_path.setText(path); self._scan_folder()

    def _scan_folder(self):
        path = self.edit_path.text().strip()
        if not path or not os.path.exists(path): self._status("Dossier introuvable."); return
        try:
            self._experiences = scan_experiment_folder(path)
            self.list_exp.clear(); self.combo_2d.clear(); self.combo_13c.clear()
            for exp in self._experiences:
                self.list_exp.addItem(f"{exp['num']}  —  {exp['pulprog']}  [{exp['dim']}D]")
                if exp["dim"]==2: self.combo_2d.addItem(f"{exp['num']}  —  {exp['pulprog']}", userData=exp)
                else: self.combo_13c.addItem(f"{exp['num']}  —  {exp['pulprog']}", userData=exp)
            self._add_to_history(path)
            # Auto-suggest best experiments
            suggested_1h, suggested_2d, suggested_13c = self._suggest_experiments()
            if suggested_1h is not None:
                self.list_exp.setCurrentRow(suggested_1h)
                self._select_proton(self.list_exp.item(suggested_1h))
            if suggested_2d is not None:
                self.combo_2d.setCurrentIndex(suggested_2d)
            if suggested_13c is not None:
                self.combo_13c.setCurrentIndex(suggested_13c)
                self._load_13c()  # Auto-load ¹³C spectrum
            self._status(f"{len(self._experiences)} expérience(s) — suggestions appliquées.")
        except Exception as e: self._status(f"Erreur scan : {e}")

    def _suggest_experiments(self) -> tuple:
        """
        Suggests the most likely experiments based on pulprog names and dimension.
        Returns (idx_1h, idx_2d, idx_13c) or (None, None, None) if not found.
        Common pulse programs:
        - 1D: zg, zgpr, zgpg30, etc. (protons are simpler, usually just 'zg')
        - 2D: hsqc, hmqc, hsqcead, etc.
        - 13C: zgpg30 (proton-decoupled carbon)
        """
        idx_1h = idx_2d = idx_13c = None
        
        # Look for 1H spectrum (lowest number, usually earliest experiment)
        for i, exp in enumerate(self._experiences):
            pulprog = exp['pulprog'].lower()
            if exp['dim'] == 1 and 'zg' in pulprog and 'zg' == pulprog[:2]:
                idx_1h = i
                break
        # Fallback: any 1D that's not zgpg30
        if idx_1h is None:
            for i, exp in enumerate(self._experiences):
                if exp['dim'] == 1 and 'zgpg' not in exp['pulprog'].lower():
                    idx_1h = i
                    break
        
        # Look for 2D spectrum (prefer hsqc, hmqc, hsqcead)
        for preferred in ['hsqc', 'hmqc', 'hsqcead']:
            for i in range(self.combo_2d.count()):
                if preferred in self.combo_2d.itemText(i).lower():
                    idx_2d = i
                    break
            if idx_2d is not None:
                break
        # Fallback: first 2D experiment
        if idx_2d is None and self.combo_2d.count() > 0:
            idx_2d = 0
        
        # Look for 13C spectrum (prefer zgpg30)
        for i in range(self.combo_13c.count()):
            if 'zgpg' in self.combo_13c.itemText(i).lower():
                idx_13c = i
                break
        # Fallback: first 13C-like experiment
        if idx_13c is None and self.combo_13c.count() > 0:
            idx_13c = 0
        
        return idx_1h, idx_2d, idx_13c

    def _select_proton(self, item):
        idx = self.list_exp.row(item); exp = self._experiences[idx]
        if exp["dim"]!=1: self._status(f"Exp {exp['num']} est 2D."); return
        try:
            self._ppm, self._intensites = load_proton_spectrum(exp["path"])
            self._status(f"¹H : exp {exp['num']} ({exp['pulprog']}) — {len(self._ppm)} pts.")
        except Exception as e: self._status(f"Erreur : {e}")

    def _load_13c(self):
        idx = self.combo_13c.currentIndex()
        if idx<0: return
        exp = self.combo_13c.itemData(idx)
        try:
            self._ppm_13c, self._int_13c = load_proton_spectrum(exp["path"])
            self._status(f"¹³C : exp {exp['num']} ({exp['pulprog']})")
        except Exception as e: self._status(f"Erreur : {e}")

    def _display_1d(self):
        if self._ppm is None: self._status("Aucun spectre ¹H chargé."); return
        raw = self.text_hsqc.toPlainText().strip()
        if raw:
            try:
                tol = self.spin_tol.value(); df = parse_hsqc_table(raw)
                self._groupes = group_by_carbon(df, tolerance=tol)
                self._couleurs = assign_colors(self._groupes)
                self.canvas_2d.set_peaks(df, tolerance=tol)
            except Exception as e: self._status(f"Erreur : {e}"); return
        else: self._groupes = self._couleurs = None
        self.canvas_1d.plot(self._ppm, self._intensites, self._groupes, self._couleurs)
        self._status("Spectre ¹H affiché.")

    def _display_2d(self):
        idx = self.combo_2d.currentIndex()
        if idx<0: return
        exp = self.combo_2d.itemData(idx)
        try:
            ppm_f2, ppm_f1, data = load_2d_spectrum(exp["path"])
            self.canvas_2d.plot(ppm_f2, ppm_f1, data, exp["pulprog"],
                                ppm_13c=self._ppm_13c, int_13c=self._int_13c)
            self._status(f"2D : exp {exp['num']} ({exp['pulprog']})")
        except Exception as e: self._status(f"Erreur : {e}")

    def _display_both(self):
        """Display both 1D and 2D spectra at once."""
        self._display_1d()
        self._display_2d()

    def _export_png(self):
        if self._ppm is None: return

        # Demande la région
        dlg = QDialog(self)
        dlg.setWindowTitle("Exporter PNG")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Région à exporter :"))
        grp_btn = QButtonGroup(dlg)
        rb_full    = QRadioButton("Spectre complet"); rb_full.setChecked(True)
        rb_current = QRadioButton("Vue actuelle (zoom courant)")
        grp_btn.addButton(rb_full, 0); grp_btn.addButton(rb_current, 1)
        lay.addWidget(rb_full); lay.addWidget(rb_current)
        row = QHBoxLayout()
        btn_ok = QPushButton("Choisir le fichier...")
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(dlg.reject)
        row.addWidget(btn_ok); row.addWidget(btn_cancel)
        lay.addLayout(row)
        if dlg.exec_() != QDialog.Accepted: return

        use_current = rb_current.isChecked()
        xlim = self.canvas_1d.get_current_xlim() if use_current else None

        path, _ = QFileDialog.getSaveFileName(self,"Exporter PNG","spectre.png","PNG (*.png)")
        if path:
            try:
                self.canvas_1d.export_png(path, xlim=xlim)
                region = "vue actuelle" if use_current else "spectre complet"
                self._status(f"Exporté ({region}) : {path}")
            except Exception as e: self._status(f"Erreur : {e}")

    def _open_report(self):
        if self._ppm is None: self._status("Chargez d'abord le spectre ¹H."); return

        # Demande la région du spectre à inclure
        dlg = QDialog(self)
        dlg.setWindowTitle("Région du spectre")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Région à afficher dans le rapport :"))
        rb_full    = QRadioButton("Spectre complet"); rb_full.setChecked(True)
        rb_current = QRadioButton("Vue actuelle (zoom courant)")
        lay.addWidget(rb_full); lay.addWidget(rb_current)
        row = QHBoxLayout()
        btn_ok = QPushButton("OK"); btn_ok.clicked.connect(dlg.accept)
        btn_no = QPushButton("Annuler"); btn_no.clicked.connect(dlg.reject)
        row.addWidget(btn_ok); row.addWidget(btn_no); lay.addLayout(row)
        if dlg.exec_() != QDialog.Accepted: return

        xlim_range = self.canvas_1d.get_current_xlim() if rb_current.isChecked() else None
        ylim_range = self.canvas_1d.get_current_ylim() if rb_current.isChecked() else None

        mol  = getattr(self.mol_canvas, "_mol", None)
        attr = getattr(self.mol_canvas, "_attributions", {})
        all_rects = dict(self.canvas_1d.pick_rects)
        if self.canvas_1d.rects:
            all_rects["__table__"] = self.canvas_1d.rects
        name = self.edit_compound.text().strip()
        win  = ReportWindow(
            self,
            ppm           = self._ppm,
            intensites    = self._intensites,
            pick_rects    = all_rects,
            mol           = mol,
            attributions  = attr,
            compound_name = name,
            xlim_range    = xlim_range,
            ylim_range    = ylim_range
        )
        win.show()

    def _on_single_mode_toggled(self, checked: bool):
        """Active/désactive la détection groupée CH₂/CH₃."""
        self.canvas_2d.single_pick_mode = checked
        self._status("Mode pic seul activé." if checked else "Mode groupement CH₂ activé.")

    def _expand_peaks_table(self):
        """Ouvre le tableau des picks dans une fenêtre agrandie et éditable."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Tableau des picks HSQC — Vue complète")
        dlg.setMinimumSize(650, 550)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(6)

        lbl = QLabel("Le tableau ci-dessous est entièrement éditable et synchronisé avec la fenêtre principale.")
        lbl.setFont(QFont("Arial", 8)); lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#444;")
        lay.addWidget(lbl)

        # Widget PeaksTable complet (partagé via proxy)
        # On crée une nouvelle instance mais on relie les signaux
        from src.gui.peaks_table import PeaksTable as PT
        exp_table = PT()
        # Copie les données existantes
        src = self.peaks_table.table
        from PyQt5.QtWidgets import QAbstractItemView
        for r in range(src.rowCount()):
            id_item = src.item(r, self.peaks_table.COL_ID)
            dh_item = src.item(r, self.peaks_table.COL_DH)
            dc_item = src.item(r, self.peaks_table.COL_DC)
            cl_item = src.item(r, self.peaks_table.COL_COLOR)
            if not (id_item and dh_item and dc_item):
                continue
            dc_key = id_item.data(Qt.UserRole)
            try:
                dH  = float(dh_item.text())
                dC  = float(dc_item.text()) if dc_item.text() != "—" else None
                col = cl_item.background().color().name() if cl_item else "#888"
            except Exception:
                continue
            if dc_key is not None and str(dc_key).startswith("mobile_"):
                exp_table.add_mobile_pick(dc_key, dH, col)
            elif dC is not None:
                exp_table.add_pick(dc_key, [dH], dC, col)

        # Connecte les signaux pour propager les actions vers le tableau principal
        exp_table.row_deleted.connect(
            lambda dc_key, dH: (
                self._on_table_row_deleted(dc_key, dH),
                self.peaks_table.remove_pick(dc_key)
            )
        )
        exp_table.color_changed.connect(
            lambda dc_key, col: (
                self._on_table_color_changed(dc_key, col),
                self.peaks_table.update_color(dc_key, col)
            )
        )
        exp_table.row_added_manually.connect(
            lambda dH, dC: (
                self._on_table_row_added_manually(dH, dC),
            )
        )
        exp_table.table.setMinimumHeight(380)
        lay.addWidget(exp_table)

        btn_close = QPushButton("Fermer")
        btn_close.setFixedHeight(26)
        btn_close.clicked.connect(dlg.close)
        lay.addWidget(btn_close)
        dlg.exec_()

    def _status(self, msg): self.lbl_status.setText(msg)