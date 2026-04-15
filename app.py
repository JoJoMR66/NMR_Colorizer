import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from src.gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    # Police sobre et lisible
    app.setFont(QFont("Arial", 9))

    # Thème neutre et sobre
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()