# -*- coding: utf-8 -*-
"""Interface local do robô: página no navegador + API JSON, tudo em 127.0.0.1, servido por este processo.

Fluxo: a pessoa escolhe o .pfx e digita a senha (a página manda os dois para ESTE processo, em localhost),
escolhe o município da empresa e a competência e clica em "Buscar". O servidor roda o mesmo `executar()` do robô
(etapas 1 a 3: extração nas duas fontes, organização das pastas, classificação e relatório) numa thread,
mostra o andamento ao vivo e, no fim, devolve um .zip com a árvore de pastas, os XML, os PDFs e o Excel.

Segurança do que é sensível:
  • só escuta em 127.0.0.1; a API exige um token aleatório gerado por execução e embutido na página
    (um site aberto em outra aba não consegue lê-lo, então não consegue chamar a API);
  • o .pfx vai para um arquivo temporário só durante a busca e é apagado no `finally`; a senha fica num
    SenhaProvider em memória e é esquecida ao terminar; a chave privada em PEM só existe dentro do `sessao_mtls`;
  • nada do certificado entra em log.

O que fica no disco de quem usa, de propósito: o estado do robô (último NSU por CNPJ e o arquivo de outras
competências) em %LOCALAPPDATA%\\RoboNFSeTomados\\estado, para a próxima busca do mesmo CNPJ ser incremental.
"""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import json
import logging
import os
import secrets
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

RAIZ = Path(os.path.abspath(__file__)).parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import robo_nfse_tomados as robo  # noqa: E402

log = logging.getLogger('nfse_tomados.interface')

VERSAO = '1.1.0'
PORTA_PADRAO = 8747
PASTA_WEB = Path(os.path.abspath(__file__)).parent / 'web'
TIPOS = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
         '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml'}
LIMITE_CORPO = 8 * 1024 * 1024                       # um .pfx tem poucos KB; 8 MB é folga
OCIOSO_SEGUNDOS = 15 * 60                            # sem página aberta por 15 min (e sem busca) → encerra


def pasta_de_estado() -> Path:
    """Onde o robô guarda o último NSU por CNPJ entre execuções (fora da pasta temporária da busca)."""
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local' / 'share')
    return Path(base) / 'RoboNFSeTomados' / 'estado'


def fontes_reais() -> dict:
    """Os dois web services públicos. Os testes trocam esta função por clientes falsos."""
    return {'SP': robo.ClienteSaoPaulo(), 'Nacional': robo.ClienteNacional()}


def formatar_cnpj(cnpj: str) -> str:
    d = robo.digitos(cnpj)
    return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}' if len(d) == 14 else cnpj


class SenhaFixa(robo.SenhaProvider):
    """A senha digitada na página, só em memória, esquecida ao fim da busca."""

    def __init__(self, senha: str):
        self._senha = senha

    def senha(self, cnpj: str) -> str:
        if self._senha is None:
            raise LookupError('a senha do certificado já foi descartada')
        return self._senha

    def esquecer(self):
        self._senha = None


class CapturaDeLog(logging.Handler):
    """Leva as mensagens do robô (progresso, avisos, erros) para o andamento mostrado na página."""

    def __init__(self, trabalho: 'Trabalho'):
        super().__init__(logging.INFO)
        self.trabalho = trabalho

    def emit(self, record: logging.LogRecord):
        with contextlib.suppress(Exception):
            nivel = 'erro' if record.levelno >= logging.ERROR else 'aviso' if record.levelno >= logging.WARNING else 'info'
            self.trabalho.anotar(record.getMessage(), nivel)


@contextlib.contextmanager
def capturando(trabalho: 'Trabalho'):
    handler = CapturaDeLog(trabalho)
    nivel_antigo = robo.log.level
    robo.log.addHandler(handler)
    if robo.log.level > logging.INFO or robo.log.level == logging.NOTSET:
        robo.log.setLevel(logging.INFO)
    try:
        yield
    finally:
        robo.log.removeHandler(handler)
        robo.log.setLevel(nivel_antigo)


class Trabalho:
    """Uma busca (real ou simulada) rodando numa thread: andamento, resultado e o zip."""

    def __init__(self, modo: str):
        self.modo = modo                                  # 'real' ou 'simulado'
        self.id = secrets.token_hex(4)
        self.inicio = time.time()
        self.fim: Optional[float] = None
        self.fase = 'preparando'
        self.mensagens: list[dict] = []
        self.erro: Optional[str] = None
        self.concluido = False
        self.resultado: Optional[dict] = None
        self.zip_caminho: Optional[Path] = None
        self.pasta = Path(tempfile.mkdtemp(prefix='robo_nfse_'))
        self._lock = threading.Lock()

    def anotar(self, texto: str, nivel: str = 'info'):
        with self._lock:
            self.mensagens.append({'hora': dt.datetime.now().strftime('%H:%M:%S'), 'texto': str(texto), 'nivel': nivel})

    def estado(self, desde: int = 0) -> dict:
        with self._lock:
            mensagens = self.mensagens[desde:]
            total = len(self.mensagens)
        return {
            'id': self.id, 'modo': self.modo, 'fase': self.fase, 'concluido': self.concluido, 'erro': self.erro,
            'segundos': round((self.fim or time.time()) - self.inicio),
            'mensagens': mensagens, 'total_mensagens': total,
            'resultado': self.resultado if self.concluido else None,
            'zip': self.zip_caminho.name if self.zip_caminho else None,
        }

    def terminar(self, erro: Optional[str] = None):
        self.erro = erro
        self.fase = 'erro' if erro else 'concluido'
        self.concluido = True
        self.fim = time.time()

    def limpar(self):
        shutil.rmtree(self.pasta, ignore_errors=True)


# ---- montagem do resultado --------------------------------------------------------------------------------------
def _nota_json(n: robo.Nota, situacao: str, empresa: robo.Empresa) -> dict:
    return {
        'empresa_codigo': empresa.codigo, 'empresa_razao': empresa.razao,
        'fonte': n.fonte, 'numero': n.numero, 'chave': n.chave,
        'emissao': n.emissao.isoformat() if n.emissao else None,
        'prestador_nome': n.prestador_nome, 'prestador_cnpj': n.prestador_cnpj,
        'prestador_municipio_ibge': n.prestador_municipio_ibge,
        'valor': round(n.valor_servico, 2), 'aliquota': n.aliquota, 'iss': round(n.valor_iss, 2),
        'iss_retido': n.iss_retido, 'cancelada': n.cancelada, 'situacao': situacao,
    }


def resumo(resultados: list, comp: robo.Competencia) -> dict:
    """O que a página mostra: totais, uma linha por empresa e uma linha por nota."""
    notas = [(n, s) for r in resultados for n, s in r.notas]
    por_nota = [r.empresa for r in resultados for _ in r.notas]
    ativas = [n for n, _ in notas if not n.cancelada]
    return {
        'competencia': str(comp),
        'pasta_competencia': comp.pasta,
        'empresas': [{
            'codigo': r.empresa.codigo, 'razao': r.empresa.razao, 'cnpj': r.empresa.cnpj,
            'municipio_ibge': r.empresa.municipio_ibge, 'documentos_lidos': r.extraidas,
            'fora_do_municipio': r.fora_do_municipio, 'escrituradas': r.escrituradas,
            'ja_escrituradas': r.ja_escrituradas, 'pendencias': list(r.erros),
        } for r in resultados],
        'totais': {
            'documentos_lidos': sum(r.extraidas for r in resultados),
            'notas': len(notas),
            'sp': sum(1 for n, _ in notas if n.fonte == 'SP'),
            'nacional': sum(1 for n, _ in notas if n.fonte == 'Nacional'),
            'do_municipio': sum(1 for _, s in notas if s.startswith('do município')),
            'fora': sum(1 for n, s in notas if not n.cancelada and not s.startswith('do município')),
            'canceladas': sum(1 for n, _ in notas if n.cancelada),
            'valor': round(sum(n.valor_servico for n in ativas), 2),
            'iss': round(sum(n.valor_iss for n in ativas), 2),
            'iss_retido': round(sum(n.valor_iss for n in ativas if n.iss_retido), 2),
            'pendencias': sum(len(r.erros) for r in resultados),
        },
        'notas': [_nota_json(n, s, e) for (n, s), e in zip(notas, por_nota)],
    }


def zipar(origem: Path, destino: Path) -> Path:
    with zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for arquivo in sorted(origem.rglob('*')):
            if arquivo.is_file():
                zf.write(arquivo, arquivo.relative_to(origem).as_posix())
    return destino


def zipar_competencia(pasta_comp: Path, relatorios: list, razao: str, comp: robo.Competencia, destino: Path) -> Path:
    """Só a competência pedida: <razão>/NFE/<ano>/<MM-AAAA>/... e o relatório em Excel ao lado."""
    raiz = robo.nome_seguro(razao)
    with zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for arquivo in sorted(pasta_comp.rglob('*')):
            if arquivo.is_file():
                zf.write(arquivo, f'{raiz}/NFE/{comp.ano}/{pasta_comp.name}/{arquivo.relative_to(pasta_comp).as_posix()}')
        for relatorio in relatorios:
            if Path(relatorio).is_file():
                zf.write(relatorio, f'{raiz}/Relatorio NFS-e tomadas {comp.pasta}.xlsx')
    return destino


# ---- as duas buscas ---------------------------------------------------------------------------------------------
def rodar_real(trabalho: Trabalho, pfx: bytes, senha: str, comp: robo.Competencia, municipio_ibge: str,
               razao: str, desde_o_inicio: bool, fontes: Callable[[], dict], estado_em: Path):
    pasta_cert = trabalho.pasta / 'certificado'
    pasta_cert.mkdir()
    caminho_pfx = pasta_cert / 'certificado.pfx'
    senhas = SenhaFixa(senha)
    try:
        trabalho.fase = 'certificado'
        caminho_pfx.write_bytes(pfx)
        cert = robo.ler_certificado(caminho_pfx, senha)
        agora = dt.datetime.now(dt.timezone.utc)
        if cert.validade <= agora:
            raise RuntimeError(f'o certificado venceu em {cert.validade:%d/%m/%Y}; o web service recusa certificado vencido')
        # A saída é persistente, por CNPJ, como as pastas de cliente do escritório: o Sistema Nacional é
        # incremental (só manda o que é novo desde o último NSU), então a pasta precisa sobreviver entre buscas.
        base_saida = estado_em.parent / 'saida'
        empresa = robo.Empresa('1', (razao or cert.titular).strip() or cert.titular, cert.cnpj, municipio_ibge,
                               cert.cnpj, pasta=base_saida / cert.cnpj)
        trabalho.anotar(f'Certificado de {cert.titular}, CNPJ {formatar_cnpj(cert.cnpj)}, válido até {cert.validade:%d/%m/%Y}.')
        trabalho.anotar(f'Competência {comp}. Município da empresa: {municipio_ibge}.')

        estado_em.mkdir(parents=True, exist_ok=True)
        if desde_o_inicio:
            estado = robo.EstadoRobo(estado_em)
            if estado.dados['nsu'].pop(cert.cnpj, None) is not None:
                estado.gravar()
                trabalho.anotar('Último NSU descartado: a busca no Sistema Nacional recomeça do zero.', 'aviso')

        cfg = robo.Config(pasta_saida=base_saida, pasta_estado=estado_em,
                          municipio_escrituracao_ibge=municipio_ibge, pausa_entre_empresas=0)
        trabalho.fase = 'buscando'
        trabalho.anotar('Consultando a Nota Paulistana e o Sistema Nacional NFS-e…')
        resultados: list = []
        with capturando(trabalho):
            relatorios = robo.executar(cfg, comp, [empresa], senhas, {cert.cnpj: cert}, portal=None, fontes=fontes(),
                                       resultados=resultados)
        trabalho.fase = 'empacotando'
        pasta_comp = robo.pasta_da_competencia(empresa.pasta, comp)
        trabalho.resultado = resumo(resultados, comp)
        trabalho.resultado['modo'] = 'real'
        trabalho.resultado['estado_em'] = str(estado_em)
        trabalho.resultado['pasta_local'] = str(pasta_comp)
        nome = f'NFS-e tomadas {cert.cnpj} {comp.pasta}.zip'
        trabalho.zip_caminho = zipar_competencia(pasta_comp, relatorios, empresa.razao, comp, trabalho.pasta / nome)
        t = trabalho.resultado['totais']
        trabalho.anotar(f"Pronto: {t['notas']} nota(s) distinta(s) ({t['documentos_lidos']} documento(s) lido(s)), "
                        f"{t['fora']} de fora do município, {t['canceladas']} cancelada(s). Zip gerado.")
        trabalho.terminar()
    except Exception as e:  # noqa: BLE001 — qualquer falha vira mensagem na página
        trabalho.anotar(f'{type(e).__name__}: {e}', 'erro')
        trabalho.terminar(str(e) or type(e).__name__)
    finally:
        senhas.esquecer()
        shutil.rmtree(pasta_cert, ignore_errors=True)


def rodar_simulado(trabalho: Trabalho):
    try:
        trabalho.fase = 'buscando'
        trabalho.anotar('Modo simulado: seis empresas fictícias, notas geradas com semente fixa e um portal em memória.')
        comp = robo.Competencia.anterior_a(dt.date.today())
        resultados: list = []
        with capturando(trabalho):
            robo.demonstracao(trabalho.pasta / 'saida', resultados=resultados)
        trabalho.fase = 'empacotando'
        trabalho.resultado = resumo(resultados, comp)
        trabalho.resultado['modo'] = 'simulado'
        nome = f'demonstracao-nfse-tomados-{comp.pasta}.zip'
        trabalho.zip_caminho = zipar(trabalho.pasta / 'saida', trabalho.pasta / nome)
        t = trabalho.resultado['totais']
        trabalho.anotar(f"Pronto: {t['notas']} nota(s) em {len(resultados)} empresa(s), "
                        f"{sum(e['escrituradas'] for e in trabalho.resultado['empresas'])} escriturada(s) no portal simulado. Zip gerado.")
        trabalho.terminar()
    except Exception as e:  # noqa: BLE001
        trabalho.anotar(f'{type(e).__name__}: {e}', 'erro')
        trabalho.terminar(str(e) or type(e).__name__)


# ---- servidor HTTP ----------------------------------------------------------------------------------------------
class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    # No Windows, SO_REUSEADDR deixa dois processos abrirem a MESMA porta (e o segundo nem recebe as conexões);
    # sem ele, a porta ocupada dá erro e `criar_servidor` passa para a seguinte. No Linux o reuso só evita o
    # TIME_WAIT entre uma execução e outra.
    allow_reuse_address = os.name != 'nt'

    def __init__(self, endereco, fontes: Callable[[], dict] = fontes_reais, estado_em: Optional[Path] = None,
                 encerrar_ocioso: bool = False):
        super().__init__(endereco, Tratador)
        self.token = secrets.token_urlsafe(24)
        self.fontes = fontes
        self.estado_em = estado_em or pasta_de_estado()
        self.encerrar_ocioso = encerrar_ocioso
        self.trabalho: Optional[Trabalho] = None
        self.ultimo_contato = time.time()
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self.server_address[1]}/'

    def ocupado(self) -> bool:
        return bool(self.trabalho and not self.trabalho.concluido)

    def iniciar_trabalho(self, modo: str, alvo: Callable, *args) -> Trabalho:
        with self._lock:
            if self.ocupado():
                raise RuntimeError('já existe uma busca em andamento')
            if self.trabalho:
                self.trabalho.limpar()
            self.trabalho = Trabalho(modo)
            threading.Thread(target=alvo, args=(self.trabalho, *args), daemon=True, name='busca-nfse').start()
            return self.trabalho

    def limpar(self):
        with self._lock:
            if self.trabalho and not self.ocupado():
                self.trabalho.limpar()
                self.trabalho = None

    def encerrar(self):
        threading.Thread(target=self.shutdown, daemon=True).start()

    def vigiar_ociosidade(self):
        """Com a página fechada (sem consultas) e sem busca rodando, o processo se encerra sozinho."""
        while True:
            time.sleep(30)
            if self.encerrar_ocioso and not self.ocupado() and time.time() - self.ultimo_contato > OCIOSO_SEGUNDOS:
                log.info('interface ociosa há %d min — encerrando', OCIOSO_SEGUNDOS // 60)
                self.encerrar()
                return


class Tratador(BaseHTTPRequestHandler):
    server_version = f'RoboNFSe/{VERSAO}'
    protocol_version = 'HTTP/1.1'

    def log_message(self, formato, *args):            # silencioso: nada de URL com dados no console
        log.debug(formato, *args)

    # -- utilitários --
    def _responder(self, codigo: int, corpo: bytes, tipo: str, extra: Optional[dict] = None):
        self.send_response(codigo)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(corpo)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(corpo)

    def _json(self, codigo: int, dados: dict):
        self._responder(codigo, json.dumps(dados, ensure_ascii=False).encode('utf-8'), TIPOS['.json'])

    def _corpo(self) -> dict:
        tamanho = int(self.headers.get('Content-Length') or 0)
        if tamanho > LIMITE_CORPO:
            raise ValueError('corpo grande demais')
        bruto = self.rfile.read(tamanho) if tamanho else b''
        return json.loads(bruto.decode('utf-8') or '{}')

    def _autorizado(self) -> bool:
        return secrets.compare_digest(self.headers.get('X-Token') or '', self.server.token)

    def _pagina(self):
        html = (PASTA_WEB / 'index.html').read_text('utf-8')
        html = html.replace('__TOKEN__', self.server.token).replace('__VERSAO__', VERSAO)
        self._responder(200, html.encode('utf-8'), TIPOS['.html'])

    def _estatico(self, caminho: str):
        nome = caminho.lstrip('/')
        arquivo = (PASTA_WEB / nome)
        if not nome or '..' in nome or not arquivo.is_file() or arquivo.suffix not in TIPOS:
            return self._json(404, {'erro': 'não encontrado'})
        self._responder(200, arquivo.read_bytes(), TIPOS[arquivo.suffix])

    # -- rotas --
    def do_GET(self):
        caminho = urlparse(self.path).path
        if caminho == '/':
            return self._pagina()
        if not caminho.startswith('/api/'):
            return self._estatico(caminho)
        if not self._autorizado():
            return self._json(403, {'erro': 'token inválido'})
        self.server.ultimo_contato = time.time()
        if caminho == '/api/estado':
            desde = 0
            with contextlib.suppress(ValueError):
                desde = int(dict(p.split('=', 1) for p in urlparse(self.path).query.split('&') if '=' in p).get('desde', 0))
            t = self.server.trabalho
            return self._json(200, {'versao': VERSAO, 'ocupado': self.server.ocupado(),
                                    'estado_em': str(self.server.estado_em),
                                    'trabalho': t.estado(desde) if t else None})
        if caminho == '/api/baixar':
            t = self.server.trabalho
            if not (t and t.concluido and t.zip_caminho and t.zip_caminho.is_file()):
                return self._json(404, {'erro': 'não há zip pronto'})
            nome = t.zip_caminho.name.encode('ascii', 'ignore').decode() or 'nfse-tomadas.zip'
            return self._responder(200, t.zip_caminho.read_bytes(), 'application/zip',
                                   {'Content-Disposition': f'attachment; filename="{nome}"'})
        return self._json(404, {'erro': 'rota não encontrada'})

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        caminho = urlparse(self.path).path
        if not self._autorizado():
            return self._json(403, {'erro': 'token inválido'})
        self.server.ultimo_contato = time.time()
        try:
            dados = self._corpo()
        except Exception as e:  # noqa: BLE001
            return self._json(400, {'erro': f'pedido inválido: {e}'})

        if caminho == '/api/certificado':
            return self._certificado(dados)
        if caminho == '/api/buscar':
            return self._buscar(dados)
        if caminho == '/api/simular':
            try:
                t = self.server.iniciar_trabalho('simulado', rodar_simulado)
            except RuntimeError as e:
                return self._json(409, {'erro': str(e)})
            return self._json(202, {'id': t.id})
        if caminho == '/api/limpar':
            self.server.limpar()
            return self._json(200, {'ok': True})
        if caminho == '/api/encerrar':
            self._json(200, {'ok': True, 'mensagem': 'encerrando'})
            self.server.encerrar()
            return None
        return self._json(404, {'erro': 'rota não encontrada'})

    @staticmethod
    def _ler_pfx(dados: dict) -> tuple[bytes, str]:
        try:
            pfx = base64.b64decode(dados.get('pfx_b64') or '', validate=True)
        except Exception as e:  # noqa: BLE001
            raise ValueError('arquivo do certificado inválido') from e
        if not pfx:
            raise ValueError('envie o arquivo .pfx do certificado')
        return pfx, str(dados.get('senha') or '')

    def _certificado(self, dados: dict):
        """Só confere: abre o .pfx com a senha e devolve titular, CNPJ e validade. Nada fica no disco."""
        try:
            pfx, senha = self._ler_pfx(dados)
        except ValueError as e:
            return self._json(400, {'erro': str(e)})
        pasta = Path(tempfile.mkdtemp(prefix='robo_nfse_cert_'))
        try:
            caminho = pasta / 'certificado.pfx'
            caminho.write_bytes(pfx)
            cert = robo.ler_certificado(caminho, senha)
            vencido = cert.validade <= dt.datetime.now(dt.timezone.utc)
            return self._json(200, {'titular': cert.titular, 'cnpj': cert.cnpj, 'cnpj_formatado': formatar_cnpj(cert.cnpj),
                                    'validade': cert.validade.date().isoformat(), 'vencido': vencido})
        except ValueError as e:
            if 'CNPJ' in str(e):
                return self._json(400, {'erro': 'o certificado não tem CNPJ: a busca precisa do e-CNPJ da empresa tomadora'})
            return self._json(400, {'erro': 'não foi possível abrir o certificado: confira o arquivo e a senha'})
        except Exception:  # noqa: BLE001 — senha errada vira ValueError na cryptography, mas por garantia
            return self._json(400, {'erro': 'não foi possível abrir o certificado: confira o arquivo e a senha'})
        finally:
            shutil.rmtree(pasta, ignore_errors=True)

    def _buscar(self, dados: dict):
        try:
            pfx, senha = self._ler_pfx(dados)
            comp = robo.Competencia.de_texto(str(dados.get('competencia') or ''))
            municipio = robo.digitos(dados.get('municipio_ibge'))
            if len(municipio) != 7:
                raise ValueError('escolha o município da empresa (código IBGE de 7 dígitos)')
            if comp > robo.Competencia(dt.date.today().year, dt.date.today().month):
                raise ValueError('competência no futuro')
        except ValueError as e:
            return self._json(400, {'erro': str(e)})
        try:
            t = self.server.iniciar_trabalho('real', rodar_real, pfx, senha, comp, municipio,
                                             str(dados.get('razao') or ''), bool(dados.get('desde_o_inicio')),
                                             self.server.fontes, self.server.estado_em)
        except RuntimeError as e:
            return self._json(409, {'erro': str(e)})
        return self._json(202, {'id': t.id})


# ---- subida -------------------------------------------------------------------------------------------------------
def criar_servidor(porta: int = PORTA_PADRAO, fontes: Callable[[], dict] = fontes_reais,
                   estado_em: Optional[Path] = None, encerrar_ocioso: bool = False) -> Servidor:
    """Abre o servidor em 127.0.0.1. Se a porta estiver ocupada, tenta as seguintes (porta 0 = qualquer livre)."""
    ultimo_erro: Optional[Exception] = None
    candidatas = [porta] if porta == 0 else range(porta, porta + 20)
    for p in candidatas:
        try:
            return Servidor(('127.0.0.1', p), fontes=fontes, estado_em=estado_em, encerrar_ocioso=encerrar_ocioso)
        except OSError as e:
            ultimo_erro = e
    raise RuntimeError(f'não consegui abrir uma porta a partir de {porta}: {ultimo_erro}')


def iniciar_em_thread(porta: int = 0, **kw) -> Servidor:
    """Para testes e para o empacotado: sobe e volta na hora, servindo numa thread."""
    servidor = criar_servidor(porta, **kw)
    threading.Thread(target=servidor.serve_forever, daemon=True, name='interface-nfse').start()
    if servidor.encerrar_ocioso:
        threading.Thread(target=servidor.vigiar_ociosidade, daemon=True, name='vigia-ociosidade').start()
    return servidor


def iniciar(porta: int = PORTA_PADRAO, abrir_navegador: bool = True, encerrar_ocioso: bool = True, **kw) -> None:
    """Sobe a interface e fica servindo até Ctrl+C, até o botão Encerrar ou até ficar ociosa."""
    servidor = criar_servidor(porta, encerrar_ocioso=encerrar_ocioso, **kw)
    if encerrar_ocioso:
        threading.Thread(target=servidor.vigiar_ociosidade, daemon=True, name='vigia-ociosidade').start()
    log.info('Interface local do Robô NFS-e Tomados em %s (Ctrl+C encerra)', servidor.url)
    print(f'\n  Interface local: {servidor.url}\n  O certificado e a senha ficam só nesta máquina.\n', flush=True)
    if abrir_navegador:
        threading.Timer(0.6, lambda: webbrowser.open(servidor.url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.limpar()
        servidor.server_close()
        log.info('interface encerrada')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    iniciar()
