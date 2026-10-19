r"""Entrada do executável "Robo NFSe.exe": sobe a interface local e abre o navegador.

Sem console: os avisos vão para %LOCALAPPDATA%\RoboNFSe\interface.log. O processo se encerra sozinho
15 minutos depois de a página ser fechada (sem busca em andamento), ou na hora pelo botão "Encerrar" da página.
"""
import logging
import os
import sys
from pathlib import Path

TITULO = 'Robô NFS-e'


def avisar(texto: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, texto, TITULO, 0x10)
    except Exception:  # noqa: BLE001
        print(texto, file=sys.stderr)


def main() -> int:
    sys.dont_write_bytecode = True
    pasta = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'RoboNFSe'
    pasta.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=pasta / 'interface.log', level=logging.INFO, encoding='utf-8',
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    try:
        from interface.servidor import iniciar
        # ROBO_SEM_NAVEGADOR=1 só nos testes do pacote: sobe sem abrir o navegador
        iniciar(abrir_navegador=os.environ.get('ROBO_SEM_NAVEGADOR') != '1', encerrar_ocioso=True)
    except Exception as e:  # noqa: BLE001
        logging.exception('falha ao subir a interface')
        avisar(f'Não foi possível abrir a interface:\n\n{e}\n\nDetalhes em {pasta / "interface.log"}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
