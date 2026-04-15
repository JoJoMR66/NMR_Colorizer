"""
Widget d'édition de structure moléculaire basé sur Ketcher standalone.

Pré-requis :
  pip install PyQtWebEngine
  python setup_ketcher.py   (une seule fois)
"""

import os
import json
import threading
import functools
import http.server

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal, QUrl, Qt, QFile, QIODevice
from PyQt5.QtGui import QFont

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineScript
    from PyQt5.QtWebChannel import QWebChannel
    WEBENGINE_OK = True
except ImportError:
    WEBENGINE_OK = False

KETCHER_DIR  = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ketcher"
)
KETCHER_PORT = 18765


# -------------------------------------------------------------------
# Serveur HTTP local (singleton)
# -------------------------------------------------------------------

class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class _KetcherServer:
    def __init__(self):
        self._server = None
        self._thread = None

    def start(self, directory: str):
        if self._server is not None:
            return
        handler = functools.partial(_SilentHandler, directory=directory)
        try:
            self._server = http.server.HTTPServer(("localhost", KETCHER_PORT), handler)
        except OSError:
            return   # port déjà occupé
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self):
        return f"http://localhost:{KETCHER_PORT}/index.html"


_server = _KetcherServer()


# -------------------------------------------------------------------
# Pont JS <-> Python
# -------------------------------------------------------------------

class _Bridge(QObject):
    ready          = pyqtSignal()
    atoms_selected = pyqtSignal(list)
    molfile_ready  = pyqtSignal(str)

    @pyqtSlot()
    def on_ketcher_ready(self):
        self.ready.emit()

    @pyqtSlot(str)
    def on_atoms_selected(self, indices_json: str):
        try:
            self.atoms_selected.emit(json.loads(indices_json))
        except Exception:
            self.atoms_selected.emit([])

    @pyqtSlot(str)
    def on_molfile(self, molfile: str):
        self.molfile_ready.emit(molfile)


# -------------------------------------------------------------------
# Lecture du JS QWebChannel depuis les ressources Qt
# -------------------------------------------------------------------

def _read_qwebchannel_js() -> str:
    """Lit qwebchannel.js depuis les ressources Qt intégrées."""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QIODevice.ReadOnly):
        content = bytes(f.readAll()).decode("utf-8")
        f.close()
        return content
    return ""


# -------------------------------------------------------------------
# Widget principal
# -------------------------------------------------------------------

class KetcherWidget(QWidget):

    structure_ready = pyqtSignal(str)   # molfile exporté
    atom_attributed = pyqtSignal(int)   # atom_idx sélectionné

    def __init__(self, parent=None):
        super().__init__(parent)

        self._ready          = False
        self._pending_mol    = None    # molfile à charger dès que Ketcher est prêt
        self._pending_colors = {}      # {atom_idx: color}
        self._bridge         = _Bridge()
        self._bridge.ready.connect(self._on_ready)
        self._bridge.atoms_selected.connect(self._on_atoms_selected)
        self._bridge.molfile_ready.connect(self.structure_ready)

        self._build_ui()

        if not WEBENGINE_OK:
            self._show_error("PyQtWebEngine non installé",
                             "pip install PyQtWebEngine")
            return
        if not os.path.isdir(KETCHER_DIR):
            self._show_error("Ketcher non trouvé",
                             "Lancez : python setup_ketcher.py")
            return

        _server.start(KETCHER_DIR)
        self._load()

    # -------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        bar = QHBoxLayout()
        self._lbl_status = QLabel("Structure moléculaire")
        self._lbl_status.setFont(QFont("Arial", 8))
        bar.addWidget(self._lbl_status)
        bar.addStretch()

        for text, slot, tip in [
            ("✓ Valider",
             self._export_structure,
             "Exporte la structure vers le pipeline"),
            ("⬡ Attribuer l'atome sélectionné",
             self._get_selected_atoms,
             "Sélectionner un atome H puis cliquer ici,\npuis cliquer sur un rectangle ¹H"),
            ("✕ Effacer couleurs",
             self.clear_colors,
             "Supprime tous les surlignages"),
        ]:
            btn = QPushButton(text)
            btn.setFixedHeight(24)
            btn.setFont(QFont("Arial", 8))
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            bar.addWidget(btn)

        layout.addLayout(bar)

        if WEBENGINE_OK:
            self._view = QWebEngineView()
            layout.addWidget(self._view)
        else:
            self._view = None

    def _show_error(self, title: str, msg: str):
        if self._view:
            self._view.setHtml(
                f"<html><body style='background:#fff8f0;padding:20px;font-family:Arial;'>"
                f"<h3 style='color:#cc4400;'>{title}</h3><p>{msg}</p></body></html>"
            )
        self._lbl_status.setText(f"⚠ {title}")

    # -------------------------------------------------------------------
    # Chargement Ketcher + injection QWebChannel
    # -------------------------------------------------------------------

    def _load(self):
        # 1. Lit qwebchannel.js depuis les ressources Qt
        qwc_js = _read_qwebchannel_js()

        if not qwc_js:
            self._show_error(
                "qwebchannel.js introuvable",
                "Vérifiez votre installation de PyQtWebEngine."
            )
            return

        # 2. Configure le canal
        channel = QWebChannel(self._view.page())
        channel.registerObject("bridge", self._bridge)
        self._view.page().setWebChannel(channel)

        # 3. Script d'initialisation injecté AVANT le chargement de la page
        #    On embarque qwebchannel.js directement dans le script
        init_script = f"""
{qwc_js}

(function() {{
    function initBridge() {{
        new QWebChannel(qt.webChannelTransport, function(channel) {{
            window._pyBridge = channel.objects.bridge;
            var timer = setInterval(function() {{
                if (window.ketcher) {{
                    clearInterval(timer);
                    window._pyBridge.on_ketcher_ready();
                }}
            }}, 300);
        }});
    }}

    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', initBridge);
    }} else {{
        initBridge();
    }}
}})();
"""
        sc = QWebEngineScript()
        sc.setName("init_qwebchannel")
        sc.setSourceCode(init_script)
        sc.setInjectionPoint(QWebEngineScript.DocumentCreation)
        sc.setRunsOnSubFrames(False)
        sc.setWorldId(QWebEngineScript.MainWorld)
        self._view.page().scripts().insert(sc)

        self._view.load(QUrl(_server.url))

    # -------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------

    def _on_ready(self):
        self._ready = True
        self._lbl_status.setText("Ketcher prêt  —  dessinez ou importez une molécule")

        # Charge la molécule en attente si besoin
        if self._pending_mol is not None:
            self._do_load_molfile(self._pending_mol)
            self._pending_mol = None

        # Applique les couleurs en attente
        for idx, color in self._pending_colors.items():
            self._do_highlight(idx, color)
        self._pending_colors = {}

    def _on_atoms_selected(self, indices: list):
        if indices:
            idx = int(indices[0])
            self.atom_attributed.emit(idx)
            self._lbl_status.setText(
                f"Atome #{idx} sélectionné — cliquez sur un rectangle du spectre ¹H"
            )
        else:
            self._lbl_status.setText("Aucun atome sélectionné dans Ketcher.")

    # -------------------------------------------------------------------
    # API publique
    # -------------------------------------------------------------------

    def _export_structure(self):
        if not self._ready:
            return
        js = """
(function() {
    if (typeof ketcher === 'undefined') {
        window._pyBridge.on_molfile('');
        return;
    }
    ketcher.getMolfile().then(function(mol) {
        window._pyBridge.on_molfile(mol || '');
    }).catch(function() {
        window._pyBridge.on_molfile('');
    });
})();
"""
        self._view.page().runJavaScript(js)

    def _get_selected_atoms(self):
        if not self._ready:
            self._lbl_status.setText("Ketcher non prêt.")
            return
        js = """
(function() {
    try {
        var sel = ketcher.editor.selection() || {};
        var atoms = sel.atoms || [];
        window._pyBridge.on_atoms_selected(JSON.stringify(atoms));
    } catch(e) {
        window._pyBridge.on_atoms_selected('[]');
    }
})();
"""
        self._view.page().runJavaScript(js)

    def set_atom_color(self, atom_idx: int, color: str):
        if not self._ready:
            self._pending_colors[atom_idx] = color
        else:
            self._do_highlight(atom_idx, color)

    def _do_highlight(self, atom_idx: int, color: str):
        js = f"""
(function() {{
    try {{
        var atomId = {atom_idx};
        var color  = '{color}';
        var existing = [];
        try {{
            var h = ketcher.editor.highlights.get();
            existing = (h && h.atoms) ? h.atoms.slice() : [];
        }} catch(e) {{}}
        existing = existing.filter(function(h) {{ return h.id !== atomId; }});
        existing.push({{id: atomId, color: color}});
        ketcher.editor.highlights.set({{atoms: existing, bonds: []}});
    }} catch(e) {{
        console.log('Highlight error:', e.toString());
    }}
}})();
"""
        self._view.page().runJavaScript(js)

    def clear_colors(self):
        if not self._ready:
            self._pending_colors = {}
            return
        js = """
(function() {
    try { ketcher.editor.highlights.set({atoms: [], bonds: []}); }
    catch(e) { console.log('clear highlights:', e); }
})();
"""
        self._view.page().runJavaScript(js)

    def load_molfile(self, molfile: str):
        """Charge un molfile dans l'éditeur Ketcher."""
        if not self._ready:
            # Ketcher pas encore prêt -> on met en file d'attente
            self._pending_mol = molfile
            self._lbl_status.setText("Structure en attente du chargement de Ketcher...")
            return
        self._do_load_molfile(molfile)

    def _do_load_molfile(self, molfile: str):
        """Envoie le molfile à Ketcher via JS."""
        # Échappe les caractères problématiques pour le template JS
        escaped = (molfile
                   .replace("\\", "\\\\")
                   .replace("`", "\\`")
                   .replace("${", "\\${"))
        js = f"""
(function() {{
    if (typeof ketcher === 'undefined') {{
        console.log('Ketcher not ready for setMolecule');
        return;
    }}
    ketcher.setMolecule(`{escaped}`).then(function() {{
        console.log('Molecule loaded successfully');
    }}).catch(function(e) {{
        console.log('setMolecule error:', e);
        // Fallback pour versions antérieures de Ketcher
        try {{ ketcher.setMolecule(`{escaped}`); }} catch(e2) {{}}
    }});
}})();
"""
        self._view.page().runJavaScript(js)
        self._lbl_status.setText("Structure chargée dans Ketcher.")