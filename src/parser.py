import pandas as pd
import io

def parse_hsqc_table(raw_text: str) -> pd.DataFrame:
    """
    Parse un tableau HSQC collé depuis TopSpin.
    Retourne un DataFrame avec les colonnes : peak_id, dH, dC, intensity
    """
    # Nettoyage : on retire les lignes vides et les espaces superflus
    lines = [line.strip() for line in raw_text.strip().splitlines()]
    lines = [line for line in lines if line]

    # On repère la ligne d'en-tête
    header_index = None
    for i, line in enumerate(lines):
        if line.startswith("Peak"):
            header_index = i
            break

    if header_index is None:
        raise ValueError("En-tête 'Peak' introuvable dans le texte collé.")

    # On reconstruit un bloc texte propre à partir de l'en-tête
    clean_text = "\n".join(lines[header_index:])

    # Lecture avec pandas
    df = pd.read_csv(
        io.StringIO(clean_text),
        sep="\t",
        usecols=["Peak", "ν(F2) [ppm]", "ν(F1) [ppm]", "Intensity [abs]"]
    )

    # Renommage des colonnes
    df = df.rename(columns={
        "Peak":              "peak_id",
        "ν(F2) [ppm]":       "dH",
        "ν(F1) [ppm]":       "dC",
        "Intensity [abs]":   "intensity"
    })

    return df.reset_index(drop=True)