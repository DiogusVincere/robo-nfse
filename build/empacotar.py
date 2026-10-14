r"""Monta o pacote portátil para Windows da interface local: a pasta "Robo NFSe Tomados" e o zip dela.

    python build\empacotar.py
        -> dist\Robo NFSe Tomados\  e  dist\robo-nfse-tomados-v1.1.0-windows.zip
    python build\empacotar.py --versao 1.1.1 --sem-zip

Precisa do Python com as bibliotecas do requirements.txt, do reportlab (para os PDFs irem no pacote) e do
PyInstaller (pip install pyinstaller reportlab).
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(os.path.abspath(__file__)).parent.parent
NOME = 'Robo NFSe Tomados'

LEIA_ME = r"""ROBÔ NFS-e TOMADOS - interface local para Windows (versão {versao})

O que é
Uma página no seu navegador, servida por este programa em 127.0.0.1, para buscar as
NFS-e que uma empresa tomou no mês: você escolhe o certificado A1 (.pfx) da empresa,
digita a senha, escolhe o município e a competência, e recebe um .zip com os XML, os
PDFs e um relatório em Excel, já separados em "do município", "de fora" e canceladas.

Como usar
1. Descompacte este zip numa pasta qualquer.
2. Abra "Robo NFSe Tomados.exe". O navegador abre sozinho em http://127.0.0.1:8747/
   (se não abrir, digite esse endereço).
3. Na primeira vez o Windows pode avisar que o editor é desconhecido (SmartScreen).
   Clique em "Mais informações" e depois em "Executar assim mesmo".
4. Para parar, use o botão "Encerrar" da página. Com a página fechada e nenhuma busca
   em andamento, o programa se encerra sozinho depois de 15 minutos.

Onde ficam as coisas
- O certificado e a senha ficam só na memória do programa durante a busca e são
  descartados ao terminar. Nada disso vai para arquivo nem para a internet, além dos
  dois web services públicos (Prefeitura de São Paulo e Sistema Nacional NFS-e).
- As notas baixadas e o último NSU de cada CNPJ ficam em
  %LOCALAPPDATA%\RoboNFSeTomados (pastas "saida" e "estado"), para a próxima busca do
  mesmo CNPJ ser incremental. Pode apagar essa pasta quando quiser.
- Avisos do programa: %LOCALAPPDATA%\RoboNFSeTomados\interface.log.

Sem certificado à mão, o botão "Ver com dados simulados" roda o fluxo inteiro com
empresas e notas fictícias.

Código-fonte e documentação: https://github.com/DiogusVincere/robo-nfse-tomados
Licença MIT (LICENCA.txt).
"""


def rodar(comando, **kw):
    print('>', ' '.join(str(c) for c in comando))
    subprocess.run([str(c) for c in comando], check=True, **kw)


def congelar(saida: Path, trabalho: Path, versao: str) -> Path:
    ambiente = dict(os.environ, ROBO_VERSAO=versao)
    rodar([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
           '--distpath', saida, '--workpath', trabalho, RAIZ / 'build' / 'robo.spec'], env=ambiente, cwd=str(RAIZ))
    pacote = saida / NOME
    if not (pacote / f'{NOME}.exe').is_file():
        raise SystemExit(f'O PyInstaller não gerou {pacote / (NOME + ".exe")}.')
    return pacote


def documentos(pacote: Path, versao: str) -> None:
    (pacote / 'LEIA-ME.txt').write_text(LEIA_ME.format(versao=versao), encoding='utf-8-sig', newline='\r\n')
    shutil.copy(RAIZ / 'LICENSE', pacote / 'LICENCA.txt')


def compactar(pacote: Path, zip_destino: Path) -> Path:
    if zip_destino.exists():
        zip_destino.unlink()
    with zipfile.ZipFile(zip_destino, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arquivo in sorted(pacote.rglob('*')):
            if arquivo.is_file():
                zf.write(arquivo, Path(NOME) / arquivo.relative_to(pacote))
    return zip_destino


def main() -> None:
    p = argparse.ArgumentParser(description='Monta o pacote portátil da interface local.')
    p.add_argument('--versao', default='1.1.0')
    p.add_argument('--saida', default=str(RAIZ / 'dist'))
    p.add_argument('--trabalho', default=str(RAIZ / 'build' / 'pyinstaller'))
    p.add_argument('--sem-zip', action='store_true')
    args = p.parse_args()

    saida, trabalho = Path(args.saida), Path(args.trabalho)
    saida.mkdir(parents=True, exist_ok=True)
    pacote = congelar(saida, trabalho, args.versao)
    documentos(pacote, args.versao)
    tamanho = sum(f.stat().st_size for f in pacote.rglob('*') if f.is_file())
    print(f'\nPacote: {pacote}  ({tamanho / 1e6:.1f} MB)')
    if not args.sem_zip:
        destino = compactar(pacote, saida / f'robo-nfse-tomados-v{args.versao}-windows.zip')
        print(f'Zip: {destino}  ({destino.stat().st_size / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
