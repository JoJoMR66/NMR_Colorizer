PALETTE = [
    # Primaires et secondaires saturés
    "#E63946",  # rouge vif
    "#2196F3",  # bleu primaire
    "#2DC653",  # vert vif
    "#FF8C00",  # orange foncé
    "#9C27B0",  # violet
    "#00BCD4",  # cyan
    "#F7B731",  # jaune doré
    "#E91E63",  # rose fuchsia
    # Tons moyens distincts
    "#00897B",  # vert émeraude
    "#FF5722",  # rouge orangé
    "#3F51B5",  # indigo
    "#8BC34A",  # vert clair
    "#795548",  # brun chaud
    "#607D8B",  # bleu ardoise
    "#C62828",  # rouge bordeaux
    "#1565C0",  # bleu marine
    # Tons vifs supplémentaires
    "#558B2F",  # vert olive
    "#AD1457",  # rose foncé
    "#00695C",  # vert forêt
    "#4527A0",  # violet profond
    "#FF6F00",  # ambre foncé
    "#0277BD",  # bleu acier
    "#6D4C41",  # marron
    "#37474F",  # gris bleu foncé
    # Tons clairs mais distincts
    "#D81B60",  # framboise
    "#1B5E20",  # vert bouteille
    "#880E4F",  # prune
    "#004D40",  # vert sapin
    "#BF360C",  # terre brûlée
    "#01579B",  # bleu océan
    "#4A148C",  # aubergine
    "#006064",  # teal foncé
]

def assign_colors(groupes: dict) -> dict:
    """Assigne une couleur primaire unique à chaque groupe."""
    couleurs = {}
    for i, gid in enumerate(groupes):
        couleurs[gid] = PALETTE[i % len(PALETTE)]
    return couleurs