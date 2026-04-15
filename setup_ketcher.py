"""
Script à lancer une seule fois pour télécharger Ketcher standalone.
Place les fichiers dans le dossier ketcher/ à la racine du projet.
"""

import os
import sys
import json
import zipfile
import urllib.request

DEST = os.path.join(os.path.dirname(__file__), "ketcher")


def get_latest_release_url() -> tuple[str, str]:
    """Récupère l'URL du standalone zip dans la dernière release GitHub."""
    api_url = "https://api.github.com/repos/epam/ketcher/releases/latest"
    print("Récupération des infos de la dernière release...")
    req = urllib.request.Request(api_url, headers={"User-Agent": "NMR-Colorizer"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    version = data["tag_name"]
    assets  = data.get("assets", [])

    for asset in assets:
        name = asset["name"].lower()
        if "standalone" in name and name.endswith(".zip"):
            return asset["browser_download_url"], version

    raise RuntimeError(
        f"Aucun fichier standalone trouvé dans la release {version}.\n"
        f"Assets disponibles : {[a['name'] for a in assets]}"
    )


def download_with_progress(url: str, dest_file: str):
    """Télécharge un fichier avec affichage de la progression."""
    def reporthook(count, block_size, total_size):
        if total_size > 0:
            pct = int(count * block_size * 100 / total_size)
            sys.stdout.write(f"\r  {min(pct, 100)}%")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, dest_file, reporthook)
    print()  # newline après la barre


def main():
    if os.path.isdir(DEST) and os.listdir(DEST):
        print(f"Ketcher déjà présent dans {DEST}/")
        print("Supprimez le dossier pour forcer le re-téléchargement.")
        return

    try:
        url, version = get_latest_release_url()
    except Exception as e:
        print(f"Erreur API GitHub : {e}")
        print("\nTéléchargement manuel :")
        print("  1. Allez sur https://github.com/epam/ketcher/releases")
        print("  2. Téléchargez ketcher-standalone-*.zip")
        print(f"  3. Décompressez son contenu dans {DEST}/")
        sys.exit(1)

    zip_path = os.path.join(os.path.dirname(__file__), "_ketcher_tmp.zip")

    print(f"Téléchargement de Ketcher {version}...")
    print(f"  URL : {url}")
    download_with_progress(url, zip_path)

    print(f"Extraction dans {DEST}/...")
    os.makedirs(DEST, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Trouve le dossier racine dans le zip (s'il existe)
        names      = zf.namelist()
        root_dirs  = {n.split("/")[0] for n in names if "/" in n}
        common_root = (
            list(root_dirs)[0]
            if len(root_dirs) == 1 and all(n.startswith(list(root_dirs)[0]) for n in names)
            else None
        )

        for member in names:
            # Retire le dossier racine commun si présent
            if common_root:
                rel = member[len(common_root):].lstrip("/")
            else:
                rel = member

            if not rel:
                continue

            dest_path = os.path.join(DEST, rel)

            if member.endswith("/"):
                os.makedirs(dest_path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with zf.open(member) as src, open(dest_path, "wb") as dst:
                    dst.write(src.read())

    os.remove(zip_path)

    # Vérifie qu'on a un index.html
    if os.path.exists(os.path.join(DEST, "index.html")):
        print(f"\n✓ Ketcher {version} installé avec succès dans {DEST}/")
    else:
        print(f"\n⚠ Installation terminée mais index.html introuvable dans {DEST}/")
        print("Vérifiez manuellement le contenu du dossier.")


if __name__ == "__main__":
    main()