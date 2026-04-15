"""
Canvas de structure moléculaire — RDKit SVG + QGraphicsView.

Rendu vectoriel publication-quality via MolDraw2DSVG.
Interaction souris pour l'attribution proton ↔ atome.

API publique (identique à l'ancienne version matplotlib) :
  load_molecule(filepath: str) -> bool
  load_from_molblock(molblock: str) -> bool
  assign_color(atom_idx, dc_key, couleur)
  update_color_for_key(dc_key, new_color)
  clear_attributions()
  get_selected_atom() -> int | None
  on_atom_clicked: callable | None

Dépendances PyQt :
  PyQt5.QtSvg   (inclus dans l'install PyQt5 standard)
  PyQt5.QtWidgets.QGraphicsView / QGraphicsScene
"""

import re
import numpy as np
from io import BytesIO

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsView,
    QGraphicsScene, QGraphicsItem, QSizePolicy
)
from PyQt5.QtCore import Qt, QRectF, QByteArray, QPointF
from PyQt5.QtGui import QColor, QBrush, QPen, QFont
from PyQt5.QtSvg import QGraphicsSvgItem, QSvgRenderer

try:
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdDepictor
    from rdkit.Chem.Draw import rdMolDraw2D
    from rdkit.Geometry import rdGeometry
    RDKIT_OK = True
except ImportError:
    RDKIT_OK = False

# ---------------------------------------------------------------------------
# Constantes de rendu
# ---------------------------------------------------------------------------

SVG_W, SVG_H = 900, 340         # taille de génération SVG (px logiques)
CLICK_RADIUS_FRAC = 0.03         # rayon de clic en fraction de SVG_W

# Couleurs RDKit (RGB 0-1) par type d'atome
_RDKIT_COLORS = {
    "O":  (0.85, 0.10, 0.10),
    "N":  (0.05, 0.35, 0.80),
    "S":  (0.75, 0.55, 0.05),
    "P":  (0.95, 0.40, 0.10),
    "F":  (0.10, 0.70, 0.10),
    "Cl": (0.10, 0.70, 0.10),
    "Br": (0.55, 0.15, 0.10),
    "I":  (0.38, 0.00, 0.38),
}

SELECTED_COLOR_HEX = "#FFB300"   # ambre = sélectionné


def _hex_to_rdkit(hex_color: str):
    """Convertit un hex '#RRGGBB' en tuple RDKit (r, g, b) ∈ [0,1]³."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def _strip_svg_colors(svg_text: str, highlighted_atom_colors: dict) -> str:
    """
    Supprime TOUTES les couleurs de RDKit SAUF les couleurs d'attribution utilisateur.
    
    Les couleurs utilisateur (du spectre) doivent rester pour identifier les carbones.
    Les couleurs par défaut de RDKit (I=purple, N=blue, O=red, S=cyan) doivent être enlevées.
    
    Args:
        svg_text: SVG à traiter
        highlighted_atom_colors: {atom_idx: (r,g,b)} des atomes avec couleurs d'attribution (keep these!)
    """
    import re
    
    # Liste des couleurs par défaut de RDKit qui doivent être converties en noir
    # Ces valeurs sont en hex et proviennent du SVG généré par RDKit
    rdkit_default_colors = {
        '#A01EEF',  # I (purple)
        '#0000FF',  # N (blue)
        '#FF0000',  # O (red)
        '#33CCCC',  # S/F/Cl (cyan)
        '#00CC00',  # F (peut être vert)
        '#CCCC00',  # S (peut être jaune)
    }
    
    # Convertir les couleurs RDKit RGB tuples en hex pour les comparer
    # Celles-ci sont les couleurs utilisateur qui doivent être conservées
    user_colors_hex = set()
    for atom_idx, rgb_tuple in highlighted_atom_colors.items():
        if isinstance(rgb_tuple, tuple) and len(rgb_tuple) == 3:
            # Convertir (r,g,b) en #RRGGBB
            r, g, b = rgb_tuple
            hex_color = f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
            user_colors_hex.add(hex_color.upper())
    
    # Remplacer les couleurs RDKit par noir, mais préserver les couleurs utilisateur
    def replace_color(match):
        hex_code = match.group(0).upper()
        
        # Ne jamais remplacer blanc ou noir existant
        if hex_code in ('#FFFFFF', '#000000'):
            return match.group(0)
        
        # Ne jamais remplacer les couleurs utilisateur (palette du spectre)
        if hex_code in user_colors_hex:
            return match.group(0)
        
        # Remplacer les couleurs par défaut RDKit par noir
        if hex_code in rdkit_default_colors:
            return '#000000'
        
        # Pour les autres couleurs inconnues, les remplacer aussi par noir
        # (au cas où il y aurait des couleurs non listées)
        return '#000000'
    
    # Remplacer tous les hex codes
    svg_text = re.sub(r'#[0-9A-Fa-f]{6}', replace_color, svg_text)
    
    return svg_text


# ---------------------------------------------------------------------------
# Vue interactive
# ---------------------------------------------------------------------------

class _MolView(QGraphicsView):
    """QGraphicsView avec gestion du zoom molette et du clic."""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        from PyQt5.QtGui import QPainter
        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.SmoothPixmapTransform
            | QPainter.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(Qt.white))
        self.setFrameShape(self.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._click_cb = None   # set par MoleculeCanvas

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Convertit les coordonnées fenêtre → scène
            scene_pos = self.mapToScene(event.pos())
            if self._click_cb:
                self._click_cb(scene_pos.x(), scene_pos.y())
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Parser MDLCT (format Biovia Draw sur Windows)
# ---------------------------------------------------------------------------

def _parse_mdlct(raw: bytes) -> str:
    """
    Parse le format MDLCT de Biovia Draw (Windows clipboard).

    Structure : [0x00][longueur_1][ligne_1][0x00][longueur_2][ligne_2]...
      - Les octets nuls (0x00) sont des séparateurs entre les lignes
      - L'octet qui suit immédiatement chaque 0x00 est la longueur de la ligne
      - Le contenu de la ligne suit sur 'longueur' octets

    Exemple : \x00\x16  ACCLDraw...\x00'  22 23 ... V2000E   12.75...
      \x16 = 22 = longueur de "  ACCLDraw04092611382D"
      \'   = 39 = longueur de " 22 23  0  0  1  0  0  0  0  0999 V2000"
      E    = 69 = longueur de la ligne atome suivante
    """
    if not raw:
        return None
    
    def _is_valid_atom_line(line: str) -> bool:
        """Vérifie qu'une ligne de molfile est une ligne d'atome valide."""
        # Une ligne atome MOL contient: coordonnées (12 chars) + symbole (3 chars) + le reste
        # Format: xxxxx.xxxxyyyyy.yyyyzzzzz.zzzz aaa...
        # Au minimum: 3 champs numériques séparés par espaces
        parts = line.split()
        
        # Au moins 4 éléments: x, y, z, et le symbole de l'atome
        if len(parts) < 4:
            return False
        
        # Essaie de parser les 3 premières comme nombres (x, y, z)
        try:
            float(parts[0])
            float(parts[1])
            float(parts[2])
            # Le 4ème élément devrait être un symbole d'atome (C, H, N, O, etc.)
            # Au moins 1 caractère, maximum 2
            if len(parts[3]) <= 2 and parts[3][0].isalpha():
                return True
        except (ValueError, IndexError):
            pass
        
        return False
    
    try:
        lines = []
        i     = 0
        
        while i < len(raw):
            # Octet nul = séparateur, on passe à l'octet de longueur
            if raw[i] == 0:
                i += 1
                continue
            
            # Octet de longueur de la ligne
            length = raw[i]
            i += 1
            
            # Vérifie que nous avons assez de données
            if i + length <= len(raw):
                line = raw[i:i+length].decode("utf-8", errors="ignore").rstrip()  # Seulement trailing spaces!
                
                # Valide les lignes qui pourraient être des lignes d'atome
                # Les lignes d'atomy doivent avoir au moins 60 caractères en MOL format
                # Saute les lignes apparemment tronquées (< 50 chars et contiennent que des nombres initials)
                if line and not (len(line) < 50 and 
                                _is_valid_atom_line(line) and 
                                line.count(' ') < 10):  # Lignes d'atome ont beaucoup d'espaces
                    lines.append(line)
                elif line and (line[0].isalpha() or line[0].isdigit() or line[0] == ' '):
                    # Header, count line, bond/stereo lines - toujours valides
                    lines.append(line)
                
                i += length
            else:
                # Ligne tronquée en fin de buffer
                remaining = raw[i:].decode("utf-8", errors="ignore")
                
                # Cherche M  END ou M  enveloppant tout ce qui est valide
                if "M  END" in remaining:
                    # Extrait jusqu'à M  END inclus
                    end_idx = remaining.index("M  END") + len("M  END")
                    line = remaining[:end_idx].rstrip('\x00')
                    if line.strip():
                        # Découpe en lignes valides (dernière ligne complète)
                        valid_lines = line.rsplit('\n', 1)[0]
                        for subline in valid_lines.split('\n'):
                            subline = subline.rstrip()  # Seulement trailing spaces!
                            if subline:
                                lines.append(subline)
                else:
                    # Pas de "M  END" trouvé - la dernière ligne est incomplète
                    # On l'ignore pour éviter une erreur de parsing RDKit
                    print(f"[_parse_mdlct] Avertissement: dernier buffer tronqué ({len(remaining)} bytes), aucun M  END trouvé")
                break

        # Ajoute deux lignes vides après le header (convention MOL V2000)
        # Format MOL strict:
        #   Ligne 1: Nom de la molécule
        #   Ligne 2: Programme/utilisateur/date (peut être vide)
        #   Ligne 3: Commentaire (peut être vide)
        #   Ligne 4+: Counts line (nnnattt...) et atomes
        # Biovia envoie seulement [nom][counts], donc on doit ajouter 2 lignes vides
        if len(lines) >= 1 and "V2000" in lines[1] if len(lines) >= 2 else False:
            # Si le counts line est directement après le nom, insérer 2 lignes vides
            lines.insert(1, "")   # ligne 2 : program/date
            lines.insert(2, "")   # ligne 3 : commentaire

        result = "\n".join(lines)
        if any(tag in result for tag in ("M  END", "V2000", "V3000")):
            return result
        return None
    except Exception as e:
        print(f"_parse_mdlct error: {e}")
        import traceback
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Widget principal
# ---------------------------------------------------------------------------

class MoleculeCanvas(QWidget):
    """
    Affiche une structure moléculaire en SVG vectoriel (RDKit).
    Les atomes peuvent être colorés individuellement pour l'attribution RMN.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._mol          = None
        self._coords_svg   = {}    # {atom_idx: (x_svg, y_svg)} coords dans l'espace SVG
        self._attributions = {}    # {atom_idx: (dc_key, couleur_hex)}
        self._selected_idx = None
        self._svg_item     = None  # QGraphicsSvgItem courant

        self.on_atom_clicked = None   # callback(atom_idx: int)

        self.setFocusPolicy(__import__("PyQt5.QtCore", fromlist=["Qt"]).Qt.ClickFocus)
        self._build_ui()

    # -------------------------------------------------------------------
    # Construction UI
    # -------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scene = QGraphicsScene(self)
        self._view  = _MolView(self._scene, self)
        self._view._click_cb = self._on_view_click
        layout.addWidget(self._view)

        self._show_placeholder()


    # -------------------------------------------------------------------
    # Presse-papiers — Biovia / ChemDraw / MarvinSketch
    # -------------------------------------------------------------------

    def keyPressEvent(self, event):
        from PyQt5.QtCore import Qt as Qt_
        if (event.key() == Qt_.Key_V and
                event.modifiers() == Qt_.ControlModifier):
            self._paste_from_clipboard()
        else:
            super().keyPressEvent(event)

    def _paste_from_clipboard(self):
        """
        Lit le presse-papiers pour y trouver un molfile.
        Compatible avec Biovia Draw, ChemDraw, MarvinSketch.
        """
        from PyQt5.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        mime      = clipboard.mimeData()
        molblock  = None

        # --- Diagnostic : affiche TOUS les formats disponibles ---
        available = mime.formats()
        print(f"[Clipboard] Formats disponibles ({len(available)}) :")
        for fmt in available:
            raw = bytes(mime.data(fmt))
            preview = raw[:80].decode("utf-8", errors="replace").replace("\n", " ")
            print(f"  [{fmt}] ({len(raw)} bytes) : {preview!r}")

        # --- Essai 1 : format MDLCT (Biovia Draw sur Windows) ---
        # Biovia utilise "MDLCT" : lignes séparées par des octets nuls
        # Structure : [2 octets longueur header][contenu avec \x00 comme séparateurs]
        mdlct_key = next(
            (f for f in available if "MDLCT" in f), None
        )
        if mdlct_key:
            raw = bytes(mime.data(mdlct_key))
            print(f"[Clipboard] MDLCT trouvé ({len(raw)} bytes)")
            molblock = _parse_mdlct(raw)
            if molblock:
                print("[Clipboard] MDLCT parsé avec succès.")

        # --- Essai 2 : formats MIME chimiques standards ---
        if molblock is None:
            chem_fmts = [
                "chemical/x-mdl-molfile",
                "chemical/x-mdl-sdfile",
                "chemical/x-mol",
                "application/x-mdl-molfile",
                "MDL Molfile",
                "Molfile",
            ]
            for fmt in chem_fmts:
                if mime.hasFormat(fmt):
                    raw  = bytes(mime.data(fmt))
                    text = raw.decode("utf-8", errors="ignore")
                    if text.strip() and any(t in text for t in ("M  END","V2000","V3000")):
                        molblock = text
                        print(f"[Clipboard] Molfile via {fmt}")
                        break

        # --- Essai 3 : scan de tous les formats binaires ---
        if molblock is None:
            for fmt in available:
                # Ignore les formats OLE binaires lourds
                if "Embedded Object" in fmt or "Object Descriptor" in fmt:
                    continue
                try:
                    raw  = bytes(mime.data(fmt))
                    text = raw.decode("utf-8", errors="ignore")
                    if any(tag in text for tag in ("M  END", "V2000", "V3000")):
                        molblock = text
                        print(f"[Clipboard] Molfile détecté dans : {fmt}")
                        break
                except Exception:
                    continue

        # --- Essai 4 : texte brut ---
        if molblock is None and mime.hasText():
            text = mime.text()
            if any(tag in text for tag in ("M  END", "V2000", "V3000", "$$$$")):
                molblock = text
                print("[Clipboard] Molfile en texte brut.")

        if molblock is None:
            print("[Clipboard] Aucun molfile reconnu. Vérifiez les formats ci-dessus.")
            # Notification visuelle
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Presse-papiers",
                "Aucun molfile reconnu dans le presse-papiers.\n\n"
                "Dans Biovia/ChemDraw :\n"
                "  1. Sélectionnez la molécule (Ctrl+A)\n"
                "  2. Copiez (Ctrl+C)\n"
                "  3. Cliquez sur le panneau molécule\n"
                "  4. Collez (Ctrl+V)\n\n"
                "Formats disponibles dans le presse-papiers :\n" +
                "\n".join(f"  • {f}" for f in available[:15])
            )
            return

        ok = self.load_from_molblock(molblock)
        if ok:
            print("[Clipboard] Molécule chargée avec succès.")
        else:
            print("[Clipboard] Échec du chargement RDKit. Contenu :")
            print(molblock[:300])

    def _show_placeholder(self):
        self._scene.clear()
        self._svg_item = None
        txt = self._scene.addText(
            "Importer un fichier .mol ou .sdf",
            QFont("Arial", 10)
        )
        txt.setDefaultTextColor(QColor("#999999"))

    # -------------------------------------------------------------------
    # Chargement molécule
    # -------------------------------------------------------------------

    def load_molecule(self, filepath: str) -> bool:
        if not RDKIT_OK:
            print("MoleculeCanvas: RDKit not available")
            return False
        try:
            mol = None
            if filepath.lower().endswith(".sdf"):
                suppl = Chem.SDMolSupplier(filepath, removeHs=False)
                mol   = next((m for m in suppl if m is not None), None)
            else:
                # Essai 1 : lecture standard
                mol = Chem.MolFromMolFile(filepath, removeHs=False)
                if mol is None:
                    # Essai 2 : sans sanitization
                    mol = Chem.MolFromMolFile(filepath, removeHs=False, sanitize=False)
                if mol is None:
                    # Essai 3 : lecture brute du contenu
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content_mol = f.read()
                    mol = Chem.MolFromMolBlock(content_mol, removeHs=False)
                if mol is None:
                    mol = Chem.MolFromMolBlock(content_mol, removeHs=False, sanitize=False)

            print(f"MoleculeCanvas: mol={'OK' if mol else 'None'}, file={filepath}")
            if mol is None:
                return False

            # Sanitize si ce n'est pas déjà fait
            try:
                Chem.SanitizeMol(mol)
            except Exception as e:
                print(f"MoleculeCanvas: sanitize warning (continuing): {e}")

            return self._setup_mol(mol)
        except Exception as e:
            import traceback
            print(f"MoleculeCanvas load_molecule error: {e}")
            traceback.print_exc()
            return False

    def load_from_molblock(self, molblock: str) -> bool:
        if not RDKIT_OK or not molblock.strip():
            return False
        try:
            mol = Chem.MolFromMolBlock(molblock, removeHs=False)
            if mol is None:
                return False
            return self._setup_mol(mol)
        except Exception as e:
            print(f"MoleculeCanvas load_from_molblock error: {e}")
            return False

    def _setup_mol(self, mol) -> bool:
        """Initialise la molécule, calcule les coords 2D et rend le SVG."""
        # Vérifie si la molécule a déjà des coordonnées 2D valides
        has_coords = False
        try:
            conf = mol.GetConformer()
            has_coords = True
        except Exception:
            has_coords = False

        # Ajoute les H seulement s'ils ne sont pas déjà présents
        h_count = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "H")
        if h_count == 0:
            # Ajoute les H APRÈS vérification des coords existantes
            mol = Chem.AddHs(mol)
            
            # Si on avait des coords avant d'ajouter les H, recalcule avec AllChem
            # pour ajouter les coords des nouveaux H seulement
            if has_coords:
                try:
                    from rdkit.Chem import AllChem
                    # Ne recalcule que pour sanitize/setup, pas full recompute 2D
                    AllChem.Compute2DCoords(mol, kekulize=False)
                except Exception:
                    # Fallback si AllChem n'est pas dispo
                    rdDepictor.Compute2DCoords(mol)
            else:
                # Pas de coords existantes, calcule tout
                rdDepictor.Compute2DCoords(mol)
        else:
            # Les H sont déjà présents
            if not has_coords:
                # Pas de coords du tout, calcule-les
                rdDepictor.Compute2DCoords(mol)
            # Sinon garde les coords existantes

        self._mol          = mol
        self._attributions = {}
        self._selected_idx = None
        self._compute_svg_coords()
        self._render_svg()
        return True

    # -------------------------------------------------------------------
    # Coordonnées SVG des atomes
    # -------------------------------------------------------------------

    def _compute_svg_coords(self):
        """
        Calcule la position de chaque atome dans l'espace SVG (SVG_W × SVG_H).
        Utilisé pour le hit-test au clic.
        """
        if self._mol is None:
            return

        # On fait un rendu temporaire pour récupérer les coords SVG réelles
        drawer = rdMolDraw2D.MolDraw2DSVG(SVG_W, SVG_H)
        drawer.drawOptions().addAtomIndices = False
        drawer.drawOptions().additionalAtomLabelPadding = 0.1
        _apply_draw_options(drawer)
        drawer.DrawMolecule(self._mol)
        drawer.FinishDrawing()

        # Extrait les coords depuis le drawer
        self._coords_svg = {}
        for atom in self._mol.GetAtoms():
            idx = atom.GetIdx()
            pt  = drawer.GetDrawCoords(idx)
            self._coords_svg[idx] = (pt.x, pt.y)

    # -------------------------------------------------------------------
    # Rendu SVG
    # -------------------------------------------------------------------

    def _render_svg(self):
        """
        Génère le SVG avec RDKit en appliquant les couleurs d'attribution,
        puis l'affiche dans la scène Qt.
        """
        if self._mol is None:
            self._show_placeholder()
            return

        svg_bytes = self._build_svg()
        self._load_svg_into_scene(svg_bytes)

    def _build_svg(self) -> bytes:
        """Construit le SVG RDKit avec highlights."""
        mol = self._mol

        # --- Rassemble les highlights ---
        highlight_atoms  = {}   # {atom_idx: (r,g,b)}
        highlight_bonds  = {}

        for atom_idx, (dc_key, hex_color) in self._attributions.items():
            rdcolor = _hex_to_rdkit(hex_color)
            highlight_atoms[atom_idx] = rdcolor

            # Colorie aussi les C voisins non encore attribués
            atom = mol.GetAtomWithIdx(atom_idx)
            if atom.GetSymbol() == "H":
                for nb in atom.GetNeighbors():
                    if nb.GetSymbol() == "C" and nb.GetIdx() not in self._attributions:
                        highlight_atoms[nb.GetIdx()] = rdcolor
                        # Liaison H-C aussi
                        bond = mol.GetBondBetweenAtoms(atom_idx, nb.GetIdx())
                        if bond:
                            highlight_bonds[bond.GetIdx()] = rdcolor
            elif atom.GetSymbol() in ("N", "O", "S"):
                # H mobiles sur hétéroatomes : colorie aussi la liaison
                for nb in atom.GetNeighbors():
                    if nb.GetSymbol() == "H":
                        bond = mol.GetBondBetweenAtoms(atom_idx, nb.GetIdx())
                        if bond:
                            highlight_bonds[bond.GetIdx()] = rdcolor

        # Atome sélectionné (surbrillance ambre par-dessus)
        if self._selected_idx is not None:
            highlight_atoms[self._selected_idx] = _hex_to_rdkit(SELECTED_COLOR_HEX)

        # --- Rendu ---
        drawer = rdMolDraw2D.MolDraw2DSVG(SVG_W, SVG_H)
        _apply_draw_options(drawer)

        try:
            rdMolDraw2D.PrepareMolForDrawing(mol)
        except Exception as e:
            print(f"PrepareMolForDrawing warning: {e}")

        try:
            if highlight_atoms:
                drawer.DrawMolecule(
                    mol,
                    highlightAtoms=list(highlight_atoms.keys()),
                    highlightAtomColors=highlight_atoms,
                    highlightBonds=list(highlight_bonds.keys()) if highlight_bonds else [],
                    highlightBondColors=highlight_bonds if highlight_bonds else {},
                )
            else:
                drawer.DrawMolecule(mol)
        except Exception as e:
            print(f"DrawMolecule error: {e}")
            # Fallback sans highlights
            try:
                drawer.DrawMolecule(mol)
            except Exception as e2:
                print(f"DrawMolecule fallback error: {e2}")

        drawer.FinishDrawing()
        svg_text = drawer.GetDrawingText()
        
        # Supprime les couleurs par défaut d'RDKit, keep everything black
        svg_text = _strip_svg_colors(svg_text, highlight_atoms)
        
        return svg_text.encode("utf-8")

    def _load_svg_into_scene(self, svg_bytes: bytes):
        """Charge les bytes SVG dans QGraphicsScene."""
        self._scene.clear()
        self._svg_item = None

        renderer = QSvgRenderer(QByteArray(svg_bytes))
        if not renderer.isValid():
            self._show_placeholder()
            return

        svg_item = QGraphicsSvgItem()
        svg_item.setSharedRenderer(renderer)
        # Stocke le renderer pour éviter le GC
        svg_item._renderer = renderer

        self._scene.addItem(svg_item)
        self._svg_item = svg_item

        # Ajuste la vue pour afficher toute la molécule
        self._scene.setSceneRect(svg_item.boundingRect())
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._svg_item is not None:
            self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    # -------------------------------------------------------------------
    # Attribution depuis l'extérieur
    # -------------------------------------------------------------------

    def assign_color(self, atom_idx: int, dc_key, couleur: str):
        self._attributions[atom_idx] = (dc_key, couleur)
        if atom_idx == self._selected_idx:
            self._selected_idx = None
        self._render_svg()

    def update_color_for_key(self, dc_key, new_color: str):
        changed = False
        for idx, (key, _) in list(self._attributions.items()):
            if key == dc_key:
                self._attributions[idx] = (dc_key, new_color)
                changed = True
        if changed:
            self._render_svg()

    def clear_attributions(self):
        self._attributions = {}
        self._selected_idx = None
        self._render_svg()

    def get_selected_atom(self) -> int:
        return self._selected_idx

    # -------------------------------------------------------------------
    # Clic souris → hit-test sur les atomes
    # -------------------------------------------------------------------

    def _on_view_click(self, x_scene: float, y_scene: float):
        """
        x_scene, y_scene sont dans l'espace de la scène (= espace SVG
        puisque QGraphicsSvgItem place le SVG à l'origine).
        """
        if self._mol is None or not self._coords_svg:
            return

        click_radius = CLICK_RADIUS_FRAC * SVG_W

        best_idx  = None
        best_dist = float("inf")

        for atom in self._mol.GetAtoms():
            idx    = atom.GetIdx()
            symbol = atom.GetSymbol()

            # Ignore H implicites (liés à C)
            if symbol == "H":
                neighbors = [nb.GetSymbol() for nb in atom.GetNeighbors()]
                if "C" in neighbors:
                    continue

            if idx not in self._coords_svg:
                continue

            ax, ay = self._coords_svg[idx]
            dist   = np.sqrt((ax - x_scene)**2 + (ay - y_scene)**2)
            if dist < click_radius and dist < best_dist:
                best_dist = dist
                best_idx  = idx

        if best_idx is None:
            return

        # Désélectionne le précédent si différent
        if self._selected_idx is not None and self._selected_idx != best_idx:
            pass   # _render_svg redessinera sans highlight de l'ancien

        self._selected_idx = best_idx
        self._render_svg()   # regénère avec le nouvel atome sélectionné

        if self.on_atom_clicked:
            self.on_atom_clicked(best_idx)


# ---------------------------------------------------------------------------
# Options de dessin RDKit partagées
# ---------------------------------------------------------------------------

def _apply_draw_options(drawer: "rdMolDraw2D.MolDraw2DSVG"):
    """
    Configure les options de rendu publication-quality.
    On teste chaque attribut individuellement pour la compatibilité
    entre versions RDKit.
    """
    opts = drawer.drawOptions()

    # Attributs communs à toutes les versions
    _safe_set(opts, "bondLineWidth",        1.8)
    _safe_set(opts, "clearBackground",      True)
    _safe_set(opts, "backgroundColour",     (1.0, 1.0, 1.0, 1.0))
    _safe_set(opts, "addStereoAnnotation",  True)
    _safe_set(opts, "addAtomIndices",       False)

    # Taille des labels — noms différents selon la version RDKit
    _safe_set(opts, "atomLabelFontSize",           0.55)   # anciennes versions
    _safe_set(opts, "minFontSize",                 12)     # nouvelles versions
    _safe_set(opts, "maxFontSize",                 14)
    _safe_set(opts, "additionalAtomLabelPadding",  0.12)
    _safe_set(opts, "padding",                     0.10)

    # Force all atoms to black (override RDKit defaults)
    # Créer une palette noire pour tous les éléments
    _black = (0.0, 0.0, 0.0)  # RGB noir
    black_palette = {
        "C": _black,
        "H": _black,
        "N": _black,
        "O": _black,
        "S": _black,
        "P": _black,
        "F": _black,
        "Cl": _black,
        "Br": _black,
        "I": _black,
        "B": _black,
        "Si": _black,
        "Se": _black,
        "As": _black,
        "Hg": _black,
        "Pb": _black,
    }
    try:
        opts.updateAtomPalette(black_palette)
    except Exception:
        pass


def _safe_set(opts, attr: str, value):
    """Applique un attribut d'options RDKit sans planter si inconnu."""
    try:
        setattr(opts, attr, value)
    except AttributeError:
        pass