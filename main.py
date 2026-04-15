from src.loader import scan_experiment_folder, load_proton_spectrum
from src.parser import parse_hsqc_table
from src.grouper import group_by_carbon
from src.colorizer import assign_colors
from src.spectrum_viewer import display_proton_spectrum


# --- 1. Chargement du spectre ¹H ---
ROOT = r"O:\RMN500\2025\OpenLab\nmr\FLO000009AB"

experiences = scan_experiment_folder(ROOT)
proton_exp = next((e for e in experiences if e["pulprog"] == "zg"), None)

if not proton_exp:
    print("Aucun spectre ¹H (zg) trouvé.")
    exit()

ppm, intensites = load_proton_spectrum(proton_exp["path"])

# --- 2. Tableau HSQC : colle ton tableau ici ---
raw_hsqc = """Peak	ν(F2) [ppm]	ν(F1) [ppm]	Intensity [abs]	Annotation	
2	7.5009	133.4630	-29744214.25		
1	6.6443	111.1699	-13264767.25		
11	4.0862	64.5402	105352758.00		
6	4.1214	61.3821	-67070529.50		
3	2.3495	42.0614	-61275105.75		
7	1.7745	32.0295	70824487.25		
10	2.2321	32.0295	104163807.25		
8	1.6102	30.7291	85217589.75		
5	1.6102	27.7567	67001122.25		
12	2.1734	27.7567	106229580.25		
4	1.3755	19.2110	66073000.25		
9	0.9413	13.6377	-89173920.50		
"""

# --- 3. Pipeline de corrélation ---
df      = parse_hsqc_table(raw_hsqc)
groupes = group_by_carbon(df, tolerance=0.5)
couleurs = assign_colors(groupes)

# --- 4. Affichage ---
display_proton_spectrum(ppm, intensites, groupes=groupes, couleurs=couleurs)
