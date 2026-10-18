"""Punto de entrada del ejecutable empaquetado (EstimadorTCH.exe)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from app.principal import main

    sys.exit(main())
