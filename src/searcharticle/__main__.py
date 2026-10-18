"""
Package entry point.

Launch the application with:  python -m searcharticle
"""

from .gui import App


def main() -> None:
    """Create the main window and start the event loop."""
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
