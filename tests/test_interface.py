# -*- coding: utf-8 -*-
"""Interface local (interface/servidor.py): página e token, conferência do certificado, busca simulada, busca
"real" com fontes falsas (sem rede), zip da competência, validações e encerramento.

O certificado é autoassinado, gerado aqui; os web services são substituídos por clientes de mentira que devolvem
os XMLs sintéticos de test_leitura_xml: uma tomada de SP, uma tomada do Nacional e uma PRESTADA do Nacional com
retenções federais."""
import base64
import io
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    from . import suporte, test_certificado as tc, test_leitura_xml as tl
except ImportError:
    import suporte
    import test_certificado as tc
    import test_leitura_xml as tl

from interface import servidor as iface  # noqa: E402  (suporte já pôs a raiz no sys.path)

robo = suporte.robo
SENHA = 'senha-interface'
# a nota nacional sintética com emissão e processamento dentro de 09/2026
XML_NACIONAL_SET = (tl.XML_NACIONAL
                    .replace('2026-09-30T23:59:00-03:00', '2026-09-20T10:00:00-03:00')
                    .replace('2026-10-01T08:00:00-03:00', '2026-09-20T09:00:00-03:00'))


class FonteSPFalsa:
    def consultar_recebidas(self, cert, senha, comp):
        robo.log.info('Nota Paulistana (tomadas): página 1, 1 nota(s)')
        return [tl.XML_SP]

    def consultar_emitidas(self, cert, senha, comp):
        robo.log.info('Nota Paulistana (prestadas): página 1, 0 nota(s)')
        return []


class FonteNacionalFalsa:
    """NSU 7: a tomada; NSU 8: a prestada (a distribuição devolve tudo em que o CNPJ aparece)."""

    def distribuir(self, cert, senha, ultimo_nsu):
        docs = [{'nsu': 7, 'chave': tl.CHAVE_NACIONAL, 'tipo': 'NFSE', 'xml': XML_NACIONAL_SET},
                {'nsu': 8, 'chave': tl.CHAVE_PRESTADA, 'tipo': 'NFSE', 'xml': tl.XML_PRESTADA}]
        novos = [d for d in docs if d['nsu'] > ultimo_nsu]
        return novos, max([ultimo_nsu] + [d['nsu'] for d in novos])


def fontes_falsas():
    return {'SP': FonteSPFalsa(), 'Nacional': FonteNacionalFalsa()}


class TestInterface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.pasta = Path(cls._tmp.name)
        chave, cert = tc._certificado(f'EMPRESA EXEMPLO A LTDA:{suporte.CNPJ_A}')
        cls.pfx_b64 = base64.b64encode(tc._pfx(cls.pasta / 'a.pfx', chave, cert, SENHA).read_bytes()).decode()
        cls.servidor = iface.iniciar_em_thread(porta=0, fontes=fontes_falsas, estado_em=cls.pasta / 'dados' / 'estado')
        cls.url = cls.servidor.url.rstrip('/')
        cls.token = cls.servidor.token

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls._tmp.cleanup()

    def pedir(self, metodo, rota, corpo=None, token=True, bruto=False):
        dados = json.dumps(corpo).encode('utf-8') if corpo is not None else None
        req = urllib.request.Request(self.url + rota, data=dados, method=metodo)
        if token:
            req.add_header('X-Token', self.token)
        if dados is not None:
            req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                conteudo = r.read()
                return r.status, (conteudo if bruto else json.loads(conteudo or b'{}')), dict(r.headers)
        except urllib.error.HTTPError as e:
            conteudo = e.read()
            return e.code, (conteudo if bruto else json.loads(conteudo or b'{}')), dict(e.headers)

    def esperar(self, limite=90):
        fim = time.time() + limite
        while time.time() < fim:
            _, est, _ = self.pedir('GET', '/api/estado')
            if est['trabalho'] and est['trabalho']['concluido']:
                return est['trabalho']
            time.sleep(0.2)
        self.fail('a busca não terminou a tempo')

    def test_01_pagina_token_e_estaticos(self):
        status, html, cab = self.pedir('GET', '/', token=False, bruto=True)
        self.assertEqual(status, 200)
        self.assertIn(self.token, html.decode('utf-8'))                    # o token vai dentro da página
        self.assertIn('no-store', cab.get('Cache-Control', ''))
        self.assertEqual(self.pedir('GET', '/estilo.css', token=False, bruto=True)[0], 200)
        self.assertEqual(self.pedir('GET', '/app.js', token=False, bruto=True)[0], 200)
        status, lista, _ = self.pedir('GET', '/municipios.json', token=False)
        self.assertGreater(len(lista), 5000)
        self.assertIn(['3509502', 'Campinas', 'SP'], lista)
        self.assertEqual(self.pedir('GET', '/nao-existe.css', token=False)[0], 404)
        self.assertEqual(self.pedir('GET', '/../robo_nfse.py', token=False)[0], 404)
        # a API só responde com o token
        self.assertEqual(self.pedir('GET', '/api/estado', token=False)[0], 403)
        self.assertEqual(self.pedir('POST', '/api/simular', {}, token=False)[0], 403)
        status, est, _ = self.pedir('GET', '/api/estado')
        self.assertEqual(status, 200)
        self.assertFalse(est['ocupado'])
        self.assertIsNone(est['trabalho'])
        self.assertEqual(self.pedir('GET', '/api/baixar')[0], 404)

    def test_02_conferir_certificado(self):
        status, info, _ = self.pedir('POST', '/api/certificado', {'pfx_b64': self.pfx_b64, 'senha': SENHA})
        self.assertEqual(status, 200, info)
        self.assertEqual(info['cnpj'], suporte.CNPJ_A)
        self.assertEqual(info['titular'], 'EMPRESA EXEMPLO A LTDA')
        self.assertEqual(info['cnpj_formatado'], '15.881.399/0001-34')
        self.assertFalse(info['vencido'])
        status, erro, _ = self.pedir('POST', '/api/certificado', {'pfx_b64': self.pfx_b64, 'senha': 'errada'})
        self.assertEqual(status, 400)
        self.assertIn('senha', erro['erro'])
        status, erro, _ = self.pedir('POST', '/api/certificado', {'pfx_b64': base64.b64encode(b'lixo').decode(), 'senha': 'x'})
        self.assertEqual(status, 400)
        status, erro, _ = self.pedir('POST', '/api/certificado', {'pfx_b64': '', 'senha': 'x'})
        self.assertEqual(status, 400)
        self.assertIn('.pfx', erro['erro'])
        # nada do certificado fica no disco depois de conferir
        self.assertFalse(list(Path(tempfile.gettempdir()).glob('robo_nfse_cert_*')))

    def test_03_validacoes_da_busca(self):
        base = {'pfx_b64': self.pfx_b64, 'senha': SENHA, 'competencia': '09/2026', 'municipio_ibge': '3509502'}
        self.assertEqual(self.pedir('POST', '/api/buscar', dict(base, municipio_ibge='35'))[0], 400)
        self.assertEqual(self.pedir('POST', '/api/buscar', dict(base, competencia='13/2026'))[0], 400)
        self.assertEqual(self.pedir('POST', '/api/buscar', dict(base, competencia='01/2999'))[0], 400)
        self.assertEqual(self.pedir('POST', '/api/buscar', dict(base, pfx_b64=''))[0], 400)
        self.assertEqual(self.pedir('POST', '/api/buscar', dict(base, pfx_b64='%%%'))[0], 400)
        status, erro, _ = self.pedir('POST', '/api/buscar', dict(base, papeis=[]))
        self.assertEqual(status, 400)
        self.assertIn('tomadas', erro['erro'])
        self.assertEqual(self.pedir('POST', '/api/buscar', dict(base, papeis=['intermediada']))[0], 400)
        self.assertEqual(self.pedir('POST', '/api/buscar', dict(base, papeis='tomada'))[0], 400)
        self.assertEqual(self.pedir('POST', '/api/nao-existe', {})[0], 404)

    def test_04_busca_simulada(self):
        status, resp, _ = self.pedir('POST', '/api/simular', {})
        self.assertEqual(status, 202, resp)
        t = self.esperar()
        self.assertIsNone(t['erro'], t['mensagens'][-3:])
        self.assertEqual(t['modo'], 'simulado')
        res = t['resultado']
        self.assertEqual(res['modo'], 'simulado')
        self.assertEqual(len(res['empresas']), 6)
        self.assertEqual(res['totais']['notas'], len(res['notas']))
        self.assertGreater(res['totais']['notas'], 20)
        self.assertEqual(res['totais']['tomadas'] + res['totais']['prestadas'], res['totais']['notas'])
        self.assertGreater(res['totais']['prestadas'], 0)
        self.assertGreater(res['totais']['retido_prestadas'], 0)
        self.assertGreater(sum(e['escrituradas'] for e in res['empresas']), 0)
        self.assertTrue(all('retencoes' in n and 'papel' in n for n in res['notas']))
        self.assertTrue(any('Pronto' in m['texto'] for m in t['mensagens']))
        self.assertTrue(t['zip'].startswith('demonstracao-nfse-'))
        status, corpo, cab = self.pedir('GET', '/api/baixar', bruto=True)
        self.assertEqual(status, 200)
        self.assertIn('attachment', cab.get('Content-Disposition', ''))
        with zipfile.ZipFile(io.BytesIO(corpo)) as zf:
            nomes = zf.namelist()
        self.assertTrue(any(n.endswith('.xlsx') for n in nomes))
        self.assertTrue(any('/Notas Escrituradas/' in n for n in nomes))
        self.assertTrue(any('/Prestados/Prestados ' in n for n in nomes))
        self.assertEqual(self.pedir('POST', '/api/limpar', {})[0], 200)
        self.assertIsNone(self.pedir('GET', '/api/estado')[1]['trabalho'])

    def test_05_busca_real_com_fontes_falsas(self):
        corpo = {'pfx_b64': self.pfx_b64, 'senha': 'errada', 'competencia': '09/2026', 'municipio_ibge': '3509502'}
        status, resp, _ = self.pedir('POST', '/api/buscar', corpo)
        self.assertEqual(status, 202, resp)
        t = self.esperar()
        self.assertIsNotNone(t['erro'])                                   # senha errada: falha antes de buscar
        self.assertEqual(t['fase'], 'erro')

        corpo['senha'] = SENHA
        status, resp, _ = self.pedir('POST', '/api/buscar', corpo)
        self.assertEqual(status, 202, resp)
        t = self.esperar()
        self.assertIsNone(t['erro'], t['mensagens'][-3:])
        res = t['resultado']
        self.assertEqual(res['modo'], 'real')
        self.assertEqual(res['competencia'], '09/2026')
        self.assertEqual([e['razao'] for e in res['empresas']], ['EMPRESA EXEMPLO A LTDA'])
        self.assertEqual(res['empresas'][0]['cnpj'], suporte.CNPJ_A)
        tot = res['totais']
        self.assertEqual(tot['documentos_lidos'], 3)
        self.assertEqual(tot['notas'], 3)
        self.assertEqual((tot['tomadas'], tot['prestadas']), (2, 1))
        self.assertEqual((tot['sp'], tot['nacional']), (1, 2))
        self.assertEqual(tot['fora'], 2)                                  # as duas tomadas são de outros municípios
        self.assertEqual(tot['iss_retido'], 125.0)                        # 50 (SP, retido) + 75 (Nacional, retido)
        self.assertEqual(tot['retido_tomadas'], 125.0)
        self.assertEqual(tot['retido_prestadas'], 171.5)                  # INSS 110 + IRRF 15 + CSRF 46,50
        self.assertEqual(tot['com_retencao'], 3)
        self.assertEqual(tot['conferir'], 0)
        self.assertEqual(sorted(n['numero'] for n in res['notas']), ['4521', '501', '88'])
        prestada = next(n for n in res['notas'] if n['papel'] == 'prestada')
        self.assertEqual(prestada['numero'], '501')
        self.assertEqual(prestada['situacao'], 'prestada — com retenção')
        self.assertEqual(prestada['contraparte'], 'Cliente Exemplo B')
        self.assertEqual(prestada['retencoes']['inss'], 110.0)
        self.assertEqual(prestada['retencoes']['csrf_quais'], 'PIS+COFINS+CSLL')
        self.assertEqual(prestada['retencoes_lista'], ['INSS', 'IRRF', 'CSRF (PIS+COFINS+CSLL)'])
        self.assertEqual(prestada['valor_liquido'], 828.5)
        self.assertTrue(all(n['situacao'].startswith('fora do município') for n in res['notas'] if n['papel'] == 'tomada'))
        self.assertTrue(any('Certificado de EMPRESA EXEMPLO A LTDA' in m['texto'] for m in t['mensagens']))
        self.assertTrue(any('notas tomadas e notas prestadas' in m['texto'] for m in t['mensagens']))
        self.assertTrue(t['zip'].startswith(f'NFS-e {suporte.CNPJ_A} 09-2026'))

        status, zipado, _ = self.pedir('GET', '/api/baixar', bruto=True)
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(zipado)) as zf:
            nomes = zf.namelist()
        self.assertIn('EMPRESA EXEMPLO A LTDA/NFE/2026/09-2026/Tomados/Tomados SP/Autorizadas/Prestador Exemplo 1 NF 4521.xml', nomes)
        self.assertIn('EMPRESA EXEMPLO A LTDA/NFE/2026/09-2026/Tomados/Tomados Portal Nacional/Autorizadas/Prestador Exemplo 2 NF 88.xml', nomes)
        self.assertIn('EMPRESA EXEMPLO A LTDA/NFE/2026/09-2026/Prestados/Prestados Portal Nacional/Autorizadas/Cliente Exemplo B NF 501.xml', nomes)
        self.assertIn('EMPRESA EXEMPLO A LTDA/Relatorio NFS-e 09-2026.xlsx', nomes)

        # a saída é persistente por CNPJ e o NSU ficou guardado: a 2ª busca é incremental e devolve as mesmas notas
        pasta_local = Path(res['pasta_local'])
        self.assertTrue(pasta_local.is_dir())
        self.assertEqual(robo.EstadoRobo(self.pasta / 'dados' / 'estado').ultimo_nsu(suporte.CNPJ_A), 8)
        status, resp, _ = self.pedir('POST', '/api/buscar', corpo)
        self.assertEqual(status, 202)
        t2 = self.esperar()
        self.assertIsNone(t2['erro'], t2['mensagens'][-3:])
        self.assertEqual(sorted(n['numero'] for n in t2['resultado']['notas']), ['4521', '501', '88'])
        self.assertEqual(t2['resultado']['totais']['retido_prestadas'], 171.5)

        # só as tomadas: a prestada já salva na pasta não entra, e nada do Nacional se perde
        status, resp, _ = self.pedir('POST', '/api/buscar', dict(corpo, papeis=['tomada']))
        self.assertEqual(status, 202)
        t3 = self.esperar()
        self.assertIsNone(t3['erro'], t3['mensagens'][-3:])
        self.assertEqual(sorted(n['numero'] for n in t3['resultado']['notas']), ['4521', '88'])
        self.assertEqual(t3['resultado']['totais']['prestadas'], 0)
        self.assertTrue(any('Buscando notas tomadas.' in m['texto'] for m in t3['mensagens']))
        # o certificado temporário foi apagado
        self.assertFalse(list(Path(tempfile.gettempdir()).glob('robo_nfse_*/certificado')))
        self.pedir('POST', '/api/limpar', {})

    def test_06_duas_buscas_ao_mesmo_tempo_e_encerrar(self):
        outro = iface.iniciar_em_thread(porta=0, fontes=fontes_falsas, estado_em=self.pasta / 'outro' / 'estado')
        try:
            def pedir(rota, corpo=None):
                dados = json.dumps(corpo).encode() if corpo is not None else None
                req = urllib.request.Request(outro.url.rstrip('/') + rota, data=dados, method='POST' if dados is not None else 'GET')
                req.add_header('X-Token', outro.token)
                if dados is not None:
                    req.add_header('Content-Type', 'application/json')
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        return r.status, json.loads(r.read() or b'{}')
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read() or b'{}')
            self.assertEqual(pedir('/api/simular', {})[0], 202)
            status, erro = pedir('/api/simular', {})
            self.assertIn(status, (202, 409))                             # 409 se a 1ª ainda estava rodando
            fim = time.time() + 60
            while time.time() < fim and pedir('/api/estado')[1]['ocupado']:
                time.sleep(0.2)
            self.assertEqual(pedir('/api/encerrar', {})[0], 200)
            time.sleep(0.5)
            with self.assertRaises((urllib.error.URLError, ConnectionError, OSError)):
                urllib.request.urlopen(outro.url, timeout=2)
        finally:
            outro.server_close()


if __name__ == '__main__':
    unittest.main()
