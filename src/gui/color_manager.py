"""
Gestion des couleurs pour le pick peaking.
Palette de 20 couleurs à contraste maximal (distances perceptuelles optimisées).
"""

# Palette ordonnée pour contraste maximal entre groupes consécutifs
# Hues espacées de ~18° minimum, saturation/luminosité variées
HIGH_CONTRAST_PALETTE = [
    "#E63946",  # rouge vif
    "#2196F3",  # bleu primaire
    "#2DC653",  # vert vif
    "#FF8C00",  # orange foncé
    "#9C27B0",  # violet
    "#00BCD4",  # cyan
    "#F7B731",  # jaune doré
    "#E91E63",  # rose fuchsia
    "#00897B",  # vert émeraude
    "#FF5722",  # rouge orangé
    "#3F51B5",  # indigo
    "#8BC34A",  # vert clair
    "#795548",  # brun
    "#607D8B",  # bleu gris
    "#C62828",  # rouge foncé
    "#1565C0",  # bleu marine
    "#558B2F",  # vert olive
    "#AD1457",  # rose foncé
    "#00695C",  # vert foncé
    "#4527A0",  # violet foncé
]


class ColorManager:
    """
    Attribue et gère les couleurs des groupes de pics.
    Chaque groupe (identifié par un δC arrondi) reçoit une couleur unique.
    """

    def __init__(self):
        self._groups  = {}   # {dc_key: {"color": hex, "peaks": [(dH,dC),...]}}
        self._counter = 0

    def reset(self):
        self._groups  = {}
        self._counter = 0

    def next_color(self) -> str:
        color = HIGH_CONTRAST_PALETTE[self._counter % len(HIGH_CONTRAST_PALETTE)]
        self._counter += 1
        return color

    def add_group(self, dc_key: float, peaks: list) -> str:
        """
        Enregistre un groupe et lui attribue une couleur.
        Retourne la couleur hex attribuée.
        """
        if dc_key in self._groups:
            return self._groups[dc_key]["color"]
        color = self.next_color()
        self._groups[dc_key] = {"color": color, "peaks": peaks}
        return color

    def set_color(self, dc_key: float, color: str):
        """Change la couleur d'un groupe existant."""
        if dc_key in self._groups:
            self._groups[dc_key]["color"] = color

    def get_color(self, dc_key: float) -> str:
        if dc_key in self._groups:
            return self._groups[dc_key]["color"]
        return "#888888"


    def remove_group_by_key(self, dc_key: float):
        """Supprime un groupe spécifique par sa clé."""
        if dc_key in self._groups:
            del self._groups[dc_key]

    def remove_last(self):
        """Supprime le dernier groupe ajouté."""
        if self._groups:
            last_key = list(self._groups.keys())[-1]
            del self._groups[last_key]
            self._counter = max(0, self._counter - 1)
            return last_key
        return None

    def all_groups(self) -> dict:
        return dict(self._groups)