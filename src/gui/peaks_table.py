"""
Tableau éditable des picks HSQC.
Colonnes : #  |  δH (ppm)  |  δC (ppm)  |  Couleur

Signaux émis :
  row_deleted(dc_key: float)
  row_edited(dc_key_old: float, dH: float, dC: float)
  color_changed(dc_key: float, color: str)
  row_added_manually(dH: float, dC: float)
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton,
    QHeaderView, QAbstractItemView, QColorDialog
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QBrush, QFont


class PeaksTable(QWidget):

    row_deleted        = pyqtSignal(object, object)  # dc_key, dH supprimés
    row_edited         = pyqtSignal(float, float, float)  # dc_key_old, dH, dC
    color_changed      = pyqtSignal(object, str)     # dc_key, hex color
    row_added_manually = pyqtSignal(float, float)    # dH, dC

    # Colonnes
    COL_ID     = 0
    COL_DH     = 1
    COL_DC     = 2
    COL_COLOR  = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False   # garde-fou anti-boucle signaux
        self._rows     = {}      # {dc_key: row_index}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # --- Tableau ---
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "δH (ppm)", "δC (ppm)", "Couleur"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_ID, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_COLOR, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setFont(QFont("Courier", 8))
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # --- Boutons ---
        btn_row = QHBoxLayout()

        btn_add = QPushButton("+ Ajouter ligne")
        btn_add.setFixedHeight(24)
        btn_add.clicked.connect(self._add_empty_row)
        btn_row.addWidget(btn_add)

        btn_del = QPushButton("✕ Supprimer")
        btn_del.setFixedHeight(24)
        btn_del.clicked.connect(self._delete_selected)
        btn_row.addWidget(btn_del)

        layout.addLayout(btn_row)

        # Connexions
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        # Touche Suppr
        self.table.keyPressEvent = self._key_press

    # -------------------------------------------------------------------
    # API publique
    # -------------------------------------------------------------------

    def add_pick(self, dc_key: float, dH_list: list, dc_val: float,
                 couleur: str):
        """
        Ajoute une ou plusieurs lignes pour un groupe.
        Chaque proton du groupe = une ligne avec son δH propre.
        """
        self._updating = True
        for dH in dH_list:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Colonne # (non éditable)
            id_item = QTableWidgetItem(str(row + 1))
            id_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            id_item.setData(Qt.UserRole, dc_key)   # stocke dc_key
            self.table.setItem(row, self.COL_ID, id_item)

            # δH
            dh_item = QTableWidgetItem(f"{dH:.4f}")
            dh_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, self.COL_DH, dh_item)

            # δC
            dc_item = QTableWidgetItem(f"{dc_val:.4f}")
            dc_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, self.COL_DC, dc_item)

            # Couleur (non éditable via texte, double-clic ouvre color picker)
            col_item = QTableWidgetItem("  ")
            col_item.setBackground(QBrush(QColor(couleur)))
            col_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, self.COL_COLOR, col_item)

            # Mémorise le mapping dc_key -> row
            self._rows[dc_key] = self._rows.get(dc_key, [])
            self._rows[dc_key].append(row)

        self._updating = False


    def add_mobile_pick(self, dc_key: str, dH: float, couleur: str):
        """
        Ajoute un proton mobile (NH2, OH) sans delta C.
        dc_key : clé string préfixée "mobile_..."
        """
        self._updating = True
        row = self.table.rowCount()
        self.table.insertRow(row)

        id_item = QTableWidgetItem(str(row + 1))
        id_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        id_item.setData(Qt.UserRole, dc_key)
        self.table.setItem(row, self.COL_ID, id_item)

        dh_item = QTableWidgetItem(f"{dH:.4f}")
        dh_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, self.COL_DH, dh_item)

        dc_item = QTableWidgetItem("—")   # pas de delta C
        dc_item.setTextAlignment(Qt.AlignCenter)
        dc_item.setForeground(QBrush(QColor("#888888")))
        self.table.setItem(row, self.COL_DC, dc_item)

        col_item = QTableWidgetItem("  ")
        col_item.setBackground(QBrush(QColor(couleur)))
        col_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, self.COL_COLOR, col_item)

        self._rows.setdefault(dc_key, []).append(row)
        self._updating = False

    def remove_pick(self, dc_key: float):
        """Supprime toutes les lignes d'un groupe."""
        rows_to_remove = self._get_rows_for_key(dc_key)
        self._updating = True
        for row in sorted(rows_to_remove, reverse=True):
            self.table.removeRow(row)
        self._renumber()
        self._rebuild_row_map()
        self._updating = False

    def update_color(self, dc_key: float, couleur: str):
        """Met à jour la couleur d'un groupe dans le tableau."""
        rows = self._get_rows_for_key(dc_key)
        self._updating = True
        for row in rows:
            item = self.table.item(row, self.COL_COLOR)
            if item:
                item.setBackground(QBrush(QColor(couleur)))
        self._updating = False

    def clear_all(self):
        self._updating = True
        self.table.setRowCount(0)
        self._rows = {}
        self._updating = False

    def get_all_picks(self) -> list:
        """
        Retourne la liste des picks sous forme de dicts :
        [{"dc_key": float, "dH": float, "dC": float, "color": str}]
        """
        result = []
        for row in range(self.table.rowCount()):
            try:
                dc_key = self.table.item(row, self.COL_ID).data(Qt.UserRole)
                dH     = float(self.table.item(row, self.COL_DH).text())
                dC     = float(self.table.item(row, self.COL_DC).text())
                color  = self.table.item(row, self.COL_COLOR).background().color().name()
                result.append({"dc_key": dc_key, "dH": dH, "dC": dC, "color": color})
            except Exception:
                pass
        return result

    # -------------------------------------------------------------------
    # Gestion interne
    # -------------------------------------------------------------------

    def _get_rows_for_key(self, dc_key: float) -> list:
        """Retourne les indices de lignes correspondant à dc_key."""
        rows = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_ID)
            if item and item.data(Qt.UserRole) == dc_key:
                rows.append(row)
        return rows

    def _renumber(self):
        """Renumérote la colonne #."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_ID)
            if item:
                item.setText(str(row + 1))

    def _rebuild_row_map(self):
        """Reconstruit le mapping dc_key -> [rows]."""
        self._rows = {}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_ID)
            if item:
                key = item.data(Qt.UserRole)
                if key not in self._rows:
                    self._rows[key] = []
                self._rows[key].append(row)

    def _add_empty_row(self):
        """Ajoute une ligne vide pour saisie manuelle."""
        self._updating = True
        row = self.table.rowCount()
        self.table.insertRow(row)

        id_item = QTableWidgetItem(str(row + 1))
        id_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        id_item.setData(Qt.UserRole, None)
        self.table.setItem(row, self.COL_ID, id_item)

        self.table.setItem(row, self.COL_DH, QTableWidgetItem(""))
        self.table.setItem(row, self.COL_DC, QTableWidgetItem(""))

        col_item = QTableWidgetItem("  ")
        col_item.setBackground(QBrush(QColor("#888888")))
        col_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, self.COL_COLOR, col_item)

        self._updating = False
        # Focus sur δH pour saisie directe
        self.table.setCurrentCell(row, self.COL_DH)
        self.table.editItem(self.table.item(row, self.COL_DH))

    def _delete_selected(self):
        rows = sorted(set(
            idx.row() for idx in self.table.selectedIndexes()
        ), reverse=True)
        for row in rows:
            self._delete_row(row)

    def _delete_row(self, row: int):
        id_item = self.table.item(row, self.COL_ID)
        dc_key  = id_item.data(Qt.UserRole) if id_item else None
        # Récupère le dH de cette ligne spécifique
        dh_item = self.table.item(row, self.COL_DH)
        try:
            dH = float(dh_item.text()) if dh_item else None
        except (ValueError, AttributeError):
            dH = None

        self._updating = True
        self.table.removeRow(row)
        self._renumber()
        self._rebuild_row_map()
        self._updating = False

        if dc_key is not None:
            self.row_deleted.emit(dc_key, dH)

    def _key_press(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_selected()
        else:
            QTableWidget.keyPressEvent(self.table, event)

    # -------------------------------------------------------------------
    # Slots signaux Qt
    # -------------------------------------------------------------------

    def _on_item_changed(self, item):
        if self._updating:
            return
        row = item.row()
        col = item.column()

        if col not in (self.COL_DH, self.COL_DC):
            return

        # Récupère les valeurs de la ligne
        try:
            dH = float(self.table.item(row, self.COL_DH).text())
            dC = float(self.table.item(row, self.COL_DC).text())
        except (ValueError, AttributeError):
            return

        id_item = self.table.item(row, self.COL_ID)
        dc_key_old = id_item.data(Qt.UserRole) if id_item else None

        if dc_key_old is None:
            # Nouvelle ligne saisie manuellement
            new_dc_key = round(dC, 4)
            self._updating = True
            id_item.setData(Qt.UserRole, new_dc_key)
            self._updating = False
            self.row_added_manually.emit(dH, dC)
        else:
            self.row_edited.emit(float(dc_key_old), dH, dC)

    def _on_cell_double_clicked(self, row: int, col: int):
        if col != self.COL_COLOR:
            return

        id_item = self.table.item(row, self.COL_ID)
        dc_key  = id_item.data(Qt.UserRole) if id_item else None

        current_color = self.table.item(row, self.COL_COLOR).background().color()
        new_color     = QColorDialog.getColor(current_color, self, "Choisir une couleur")

        if new_color.isValid() and dc_key is not None:
            self._updating = True
            # Met à jour toutes les lignes du groupe
            for r in self._get_rows_for_key(dc_key):
                self.table.item(r, self.COL_COLOR).setBackground(
                    QBrush(new_color)
                )
            self._updating = False
            self.color_changed.emit(dc_key, new_color.name())