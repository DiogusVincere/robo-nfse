# -*- mode: python ; coding: utf-8 -*-
r"""Receita do PyInstaller para o pacote portátil da interface local.

Rode por build\empacotar.py, que chama
    python -m PyInstaller --noconfirm --clean --distpath <dist> --workpath <trabalho> build\robo.spec

Sai "Robo NFSe.exe" (sem console) + _internal\ com o Python, o motor (robo_nfse.py), a interface
(interface\servidor.py + interface\web) e as bibliotecas: lxml, cryptography, requests, openpyxl e reportlab.
"""
import os
from pathlib import Path

RAIZ = Path(SPECPATH).parent  # SPECPATH é a pasta deste arquivo (build\)
NOME = 'Robo NFSe'
VERSAO = os.environ.get('ROBO_VERSAO', '2.0.1')


def gerar_icone(destino: Path):
    """Ícone do executável: documento com a dobra em âmbar, nas cores da interface."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    tam = 256
    im = Image.new('RGBA', (tam, tam), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, tam - 8, tam - 8), radius=56, fill='#1F4E5F')
    d.polygon([(80, 56), (148, 56), (184, 92), (184, 200), (80, 200)], fill='#F3F5F7')
    d.polygon([(148, 56), (148, 92), (184, 92)], fill='#C98A1B')
    for y in (128, 152, 176):
        d.rounded_rectangle((104, y, 160 if y < 176 else 140, y + 10), radius=5, fill='#1F4E5F')
    destino.parent.mkdir(parents=True, exist_ok=True)
    im.save(destino, format='ICO', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return str(destino)


def info_de_versao():
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    partes = tuple(int(p) for p in (VERSAO.split('.') + ['0', '0', '0'])[:3]) + (0,)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=partes, prodvers=partes, mask=0x3F, flags=0x0, OS=0x40004,
                          fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[StringFileInfo([StringTable('041604B0', [
            StringStruct('FileDescription', 'Robô NFS-e - interface local'),
            StringStruct('ProductName', 'Robô NFS-e'),
            StringStruct('FileVersion', VERSAO),
            StringStruct('ProductVersion', VERSAO),
            StringStruct('OriginalFilename', NOME + '.exe'),
            StringStruct('LegalCopyright', 'Licença MIT'),
        ])]), VarFileInfo([VarStruct('Translation', [1046, 1200])])])


a = Analysis(
    [str(RAIZ / 'build' / 'lancador.py')],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=[(str(RAIZ / 'interface' / 'web'), 'interface/web')],
    hiddenimports=['interface', 'interface.servidor', 'robo_nfse',
                   'reportlab.pdfgen.canvas', 'reportlab.lib.pagesizes', 'openpyxl', 'openpyxl.styles',
                   'lxml.etree', 'lxml._elementpath', 'requests',
                   'cryptography.hazmat.primitives.serialization.pkcs12', 'cryptography.hazmat.backends.openssl'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'numpy', 'pandas', 'matplotlib', 'scipy', 'IPython', 'jupyter', 'streamlit', 'rapidfuzz',
              'pdfplumber', 'pdfminer', 'xlrd', 'win32com', 'pythoncom', 'pywintypes', 'pytest', 'test',
              'idlelib', 'turtle', 'turtledemo', 'lib2to3', 'pydoc_data', 'PIL'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NOME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=gerar_icone(Path(workpath) / 'icone.ico'),
    version=info_de_versao(),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=NOME,
)
