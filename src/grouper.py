import pandas as pd

def group_by_carbon(df: pd.DataFrame, tolerance: float = 0.5) -> dict:
    """
    Regroupe les protons reliés au même carbone.
    
    Paramètres :
        df        : DataFrame issu du parseur (colonnes dH, dC, peak_id)
        tolerance : tolérance en ppm sur δC pour considérer deux pics
                    comme reliés au même carbone
    
    Retourne :
        Un dict  {groupe_id (int): {"dC": float, "protons": [dH1, dH2, ...]}}
    """
    df_sorted = df.sort_values("dC").reset_index(drop=True)
    
    groupes = {}
    groupe_id = 0
    utilises = set()

    for i, row in df_sorted.iterrows():
        if i in utilises:
            continue

        # Trouver tous les pics dont le dC est proche de celui-ci
        meme_carbone = df_sorted[
            abs(df_sorted["dC"] - row["dC"]) <= tolerance
        ]

        groupes[groupe_id] = {
            "dC":     round(row["dC"], 4),
            "peaks":  meme_carbone["peak_id"].tolist(),
            "protons": meme_carbone["dH"].tolist()
        }

        utilises.update(meme_carbone.index.tolist())
        groupe_id += 1

    return groupes