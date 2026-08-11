"""Console entry point for the standard Containerlab application definition."""

from __future__ import annotations

from .app import CONTAINERLAB_APPLICATION


def main() -> int:
    """Run the standard Containerlab application."""
    with CONTAINERLAB_APPLICATION.create() as application:
        return application.run()


if __name__ == "__main__":
    raise SystemExit(main())
