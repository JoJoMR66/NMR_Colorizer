# NMR Colorizer

A Python-based GUI application for analyzing and visualizing Nuclear Magnetic Resonance (NMR) spectroscopy data. NMR Colorizer helps researchers assign chemical shifts and molecular structures by interactively correlating ¹H, ¹³C, and 2D HSQC NMR spectra.

## Features

### Spectrum Visualization
- **1D ¹H Spectrum**: Display and analyze proton NMR spectra with interactive zoom and pan controls
- **2D HSQC Spectrum**: View heteronuclear single-quantum coherence correlations between ¹H and ¹³C
- **¹³C Vertical Scale**: Display ¹³C chemical shifts alongside 2D correlations for reference

### Interactive Tools
- **Smart Zoom Controls**: 
  - 🔍 Zoom out with one click
  - Fit to peaks automatically
  - Reset to full view for both 1D and 2D spectra
  - Auto-scope 2D to show only peaks in the zoomed region

- **Peak Picking**: 
  - Detect peaks automatically in both 1D and 2D spectra
  - Manual peak picking with right-click
  - Support for mobile protons (NH₂, OH)
  - CH₂/CH₃ multiplicity detection

- **Color-Coded Attribution**:
  - Assign colors to functional groups
  - Link NMR peaks to molecular atoms
  - Visual feedback with colored rectangles on 1D and circles on 2D

### Molecule Integration
- Import molecular structures from `.mol` and `.sdf` files
- Assign NMR peaks directly to atoms on the molecule structure
- Paste molecules from ChemDraw or Biovia with Ctrl+V

### Data Management
- **HSQC Table Import**: Paste HSQC correlation tables directly from TopSpin
- **Editable Picks Table**: Manually edit, add, or delete NMR picks
- **Experiment Suggestions**: Auto-select optimal 1D, 2D, and ¹³C experiments
- **Path History**: Quick access to previously analyzed experiments

### Export & Reporting
- Export spectra as high-resolution PNG images
- Generate comprehensive analysis reports
- Customize zoom regions before export

## Installation

### Requirements
- Python 3.8+
- PyQt5
- NumPy
- Matplotlib
- nmrglue (for Bruker NMR format support)

### Setup

1. **Clone the repository**:
```bash
git clone https://github.com/yourusername/NMR_Colorizer.git
cd NMR_Colorizer
```

2. **Create a virtual environment** (recommended):
```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

## Usage

### Starting the Application
```bash
python app.py
```

### Basic Workflow

1. **Load Experiment Folder**:
   - Click "..." to browse for a Bruker NMR experiment folder
   - Click "Scanner les expériences" to load available experiments
   - The app auto-suggests optimal experiments

2. **Load Spectra**:
   - 1D ¹H spectrum is auto-loaded
   - Select and load ¹³C (vertical) spectrum
   - Select 2D HSQC experiment
   - Click "📊 Afficher 1D + 2D" to display both spectra

3. **Import HSQC Table** (optional):
   - Copy the HSQC table from TopSpin
   - Paste into the "Copier-coller" tab
   - Click "Appliquer" to parse

4. **Pick Peaks**:
   - **Right-click on 2D spectrum** → select a group (δC value)
   - **Right-click on 1D spectrum** → add mobile protons
   - **Double-click colored rectangle** → change color

5. **Assign to Molecule**:
   - Click "Importer .mol/.sdf" to load a structure
   - Click an atom on the molecule
   - Click the corresponding rectangle on the 1D spectrum
   - Repeat for all assignments

6. **Zoom & Explore**:
   - Use **🔍 Zoom Out** button to zoom back
   - Use **Ajuster** to fit to peaks
   - Use **⟲** to reset both 1D and 2D views
   - "Vue complète 2D" shows full 2D while keeping 1D zoom

7. **Export Results**:
   - Click "Exporter PNG" to save spectrum image
   - Click "📄 Ouvrir le rapport" to view analysis report

## Project Structure

```
NMR_Colorizer/
├── app.py                    # Main application entry point
├── main.py                   # Alternative launcher
├── setup_ketcher.py          # Ketcher molecular editor setup
├── src/
│   ├── loader.py             # Bruker data loader
│   ├── parser.py             # HSQC table parser
│   ├── grouper.py            # Peak grouping logic
│   ├── colorizer.py          # Color assignment
│   └── gui/
│       ├── main_window.py    # Main GUI window
│       ├── spectrum_canvas.py     # 1D spectrum visualization
│       ├── spectrum2d_canvas.py   # 2D spectrum visualization
│       ├── molecule_canvas.py     # Molecular structure viewer
│       ├── color_manager.py       # Color management
│       ├── ketcher_widget.py      # Molecule editor integration
│       ├── peaks_table.py         # Interactive peaks table
│       ├── report_window.py       # Report generation
│       └── __init__.py
└── ketcher/                  # Ketcher molecule editor (web-based)
```

## Features in Detail

### Smart 2D Zoom
When you zoom on the 1D spectrum, the 2D automatically zooms to show only the peaks within that ppm range, eliminating blank spaces and improving clarity.

### Synchronized Views
1D and 2D spectra synchronize automatically:
- Zoom on either spectrum to pan the other
- "Vue complète 2D" resets only the 2D without affecting 1D zoom
- "⟲" reset button resets both spectra

### Auto-Peak Detection
The application automatically detects peaks in both 1D and 2D spectra using intensity thresholds and can suggest peaks for quick analysis.

### Multiplicity Support
Supports CH, CH₂, and CH₃ detection with two-color rectangles showing multiplicity patterns in the 1D spectrum.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+V   | Paste molecule from clipboard (ChemDraw/Biovia) |

## Input Formats

### Supported Spectra
- **Bruker NMR data**: Automatic detection of 1D and 2D experiments
- **Processed data**: Requires TopSpin-processed data (pdata folder)

### Supported Structures
- **MOL files** (.mol): 2D molecular structure
- **SDF files** (.sdf): Multi-molecule datasets
- **Clipboard paste**: Direct from ChemDraw or Biovia Draw

## Tips & Tricks

1. **Organize by experiments**: Best to have all related experiments in one Bruker folder
2. **Use same tolerance**: Set δC tolerance to match your expected precision (0.5–1.0 ppm typical)
3. **Check multiplicities**: Use "Pic seul" mode for precise control over peak assignments
4. **Export regions**: Use current zoom to export specific regions of interest

## Troubleshooting

### "Dossier introuvable" (Folder not found)
- Verify the path to your Bruker experiment folder
- Ensure it contains numbered experiment subdirectories (1, 2, 3, etc.)

### HSQC table import fails
- Verify table format matches TopSpin HSQC output
- Ensure columns are correctly formatted with δH (¹H) and δC (¹³C) values

### 2D spectrum appears blank
- Verify the experiment is actually a 2D (must have acqu2s file)
- Check that the data is processed in TopSpin (pdata/1 folder exists)

## License

This project is licensed under the MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Feel free to submit issues or pull requests to improve the application.

## Author

Created for NMR spectroscopy analysis and molecular structure assignment.

## Acknowledgments

- Built with **PyQt5** for the GUI
- **nmrglue** for Bruker NMR data handling
- **Matplotlib** for spectra visualization
- **Ketcher** for molecular structure editing
