# -*- mode: python ; coding: utf-8 -*-
# Receta de PyInstaller del Estimador TCH. Se corre con construir.ps1 (no a mano).
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

PRODUCTO = Path(SPECPATH)
RAIZ = PRODUCTO.parent

datas = [
    (str(PRODUCTO / "app" / "ui"), "ui"),
    (str(PRODUCTO / "recursos"), "recursos"),
    (str(RAIZ / "data" / "var_map.json"), "data"),
]
binaries = []
hiddenimports = ["mensual", "cosechas_desde_app", "modelo_en_aforos", "tkinter", "tkinter.filedialog"]
hiddenimports += collect_submodules("tchmotor") + collect_submodules("app")
for paquete in ("ee",):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(PRODUCTO / "lanzador.py")],
    pathex=[str(PRODUCTO), str(RAIZ), str(RAIZ / "scripts")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "pytest", "IPython", "notebook", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="EstimadorTCH",
    console=False,
    icon=str(PRODUCTO / "icono.ico"),
    version=str(PRODUCTO / "build" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="EstimadorTCH")
