# main.py

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from gui.main_window import ReyesMainWindow
from gui.theme import GLOBAL_STYLESHEET


# =========================================================
# PROJECT PATH
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parent


def configure_project_path() -> None:
    """
    Ensure the REYES project folder is available for imports.
    """

    project_path = str(PROJECT_ROOT)

    if project_path not in sys.path:
        sys.path.insert(0, project_path)


# =========================================================
# APPLICATION
# =========================================================

def create_application() -> QApplication:
    """
    Create the main PySide6 application.
    """

    existing_app = QApplication.instance()

    if existing_app is not None:
        return existing_app

    app = QApplication(sys.argv)

    app.setApplicationName("REYES AI")
    app.setApplicationDisplayName("REYES AI")
    app.setOrganizationName("REYES")

    app.setStyleSheet(GLOBAL_STYLESHEET)

    return app


# =========================================================
# ERROR HANDLING
# =========================================================

def show_startup_error(
    error: Exception,
) -> None:
    """
    Display a readable startup error.
    """

    error_message = (
        f"{type(error).__name__}: {error}"
    )

    traceback.print_exc()

    app = QApplication.instance()

    if app is None:
        app = QApplication(sys.argv)

    QMessageBox.critical(
        None,
        "REYES Startup Error",
        (
            "REYES could not start.\n\n"
            f"{error_message}\n\n"
            "Check the terminal for the complete traceback."
        ),
    )


# =========================================================
# MAIN
# =========================================================

def main() -> int:
    """
    Start the REYES desktop interface.
    """

    configure_project_path()

    try:
        app = create_application()

        window = ReyesMainWindow()
        window.show()

        return app.exec()

    except KeyboardInterrupt:
        return 0

    except Exception as error:
        show_startup_error(error)
        return 1


if __name__ == "__main__":
    sys.exit(main())