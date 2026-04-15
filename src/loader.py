import nmrglue as ng
import numpy as np
import os


def scan_experiment_folder(root_path: str) -> list:
    """
    Scanne un dossier d'essai Bruker et liste les expériences disponibles.
    Retourne une liste de dicts :
    {"num", "pulprog", "path", "dim"}  (dim = 1 ou 2)
    """
    experiences = []

    if not os.path.exists(root_path):
        raise FileNotFoundError(f"Dossier introuvable : {root_path}")

    for entry in sorted(os.listdir(root_path), key=lambda x: int(x) if x.isdigit() else 0):
        exp_path = os.path.join(root_path, entry)
        if not os.path.isdir(exp_path) or not entry.isdigit():
            continue
        acqus_path = os.path.join(exp_path, "acqus")
        if not os.path.exists(acqus_path):
            continue

        pulprog = _read_pulprog(acqus_path)
        dim     = _read_dim(acqus_path)

        experiences.append({
            "num":     entry,
            "pulprog": pulprog,
            "path":    exp_path,
            "dim":     dim,
        })

    return experiences


def _read_pulprog(acqus_path: str) -> str:
    with open(acqus_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("##$PULPROG"):
                return line.split("<")[1].split(">")[0].strip()
    return "inconnu"


def _read_dim(acqus_path: str) -> int:
    """Lit le nombre de dimensions depuis le fichier acqus."""
    # La présence d'un fichier acqu2s dans le même dossier indique 2D
    folder = os.path.dirname(acqus_path)
    if os.path.exists(os.path.join(folder, "acqu2s")):
        return 2
    return 1


def load_proton_spectrum(exp_path: str):
    """
    Charge un spectre 1D Bruker traité.
    Retourne (ppm_scale, intensities)
    """
    pdata_path = os.path.join(exp_path, "pdata", "1")
    if not os.path.exists(pdata_path):
        raise FileNotFoundError(
            f"Dossier pdata introuvable : {pdata_path}\n"
            "Vérifie que le spectre est traité dans TopSpin."
        )
    dic, data = ng.bruker.read_pdata(pdata_path)
    udic      = ng.bruker.guess_udic(dic, data)
    uc        = ng.fileiobase.uc_from_udic(udic)
    ppm_scale = uc.ppm_scale()
    return ppm_scale, data


def load_2d_spectrum(exp_path: str):
    """
    Charge un spectre 2D Bruker traité.
    Retourne (ppm_f2, ppm_f1, data_2d)
      ppm_f2 : axe ¹H  (axe direct,   colonnes)
      ppm_f1 : axe ¹³C (axe indirect, lignes)
      data_2d: array 2D (n_f1 x n_f2)
    """
    pdata_path = os.path.join(exp_path, "pdata", "1")
    if not os.path.exists(pdata_path):
        raise FileNotFoundError(
            f"Dossier pdata introuvable : {pdata_path}\n"
            "Vérifie que le spectre est traité dans TopSpin."
        )
    dic, data = ng.bruker.read_pdata(pdata_path)
    udic      = ng.bruker.guess_udic(dic, data)

    # Axe F2 (direct = ¹H)
    uc_f2  = ng.fileiobase.uc_from_udic(udic, dim=1)
    ppm_f2 = uc_f2.ppm_scale()

    # Axe F1 (indirect = ¹³C)
    uc_f1  = ng.fileiobase.uc_from_udic(udic, dim=0)
    ppm_f1 = uc_f1.ppm_scale()

    return ppm_f2, ppm_f1, data