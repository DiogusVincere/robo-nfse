# -*- coding: utf-8 -*-
"""Seção 7 (pastas e estado) e o salvar_xmls da seção 13."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

try:
    from . import suporte
except ImportError:
    import suporte

robo = suporte.robo
nota = suporte.nota
COMP = suporte.COMP


class TestEstadoRobo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name) / 'estado'

    def tearDown(self):
        self._tmp.cleanup()

    def test_nsu_monotonico_e_persistente(self):
        est = robo.EstadoRobo(self.pasta)
        self.assertTrue(self.pasta.is_dir())                                   # a pasta nasce no construtor
        self.assertEqual(est.ultimo_nsu(suporte.CNPJ_A), 0)
        est.guardar_nsu(suporte.CNPJ_A, 10)
        est.guardar_nsu(suporte.CNPJ_A, 5)                                     # menor: não volta
        self.assertEqual(est.ultimo_nsu(suporte.CNPJ_A), 10)
        est.guardar_nsu(suporte.CNPJ_A, 12)
        self.assertEqual(est.ultimo_nsu(suporte.CNPJ_A), 12)
        self.assertEqual(est.ultimo_nsu(suporte.CNPJ_B), 0)                   # cada CNPJ tem o seu
        self.assertEqual(robo.EstadoRobo(self.pasta).ultimo_nsu(suporte.CNPJ_A), 12)   # relido do disco

    def test_canceladas_persistem(self):
        est = robo.EstadoRobo(self.pasta)
        self.assertEqual(est.canceladas(suporte.CNPJ_A), set())
        est.registrar_canceladas(suporte.CNPJ_A, {'CH-2', 'CH-1'})
        est.registrar_canceladas(suporte.CNPJ_A, {'CH-1'})                     # repetida: não duplica
        est.registrar_canceladas(suporte.CNPJ_A, [])                           # vazio: não grava nada
        self.assertEqual(est.canceladas(suporte.CNPJ_A), {'CH-1', 'CH-2'})
        self.assertEqual(est.canceladas(suporte.CNPJ_B), set())                # por CNPJ
        relido = robo.EstadoRobo(self.pasta)
        self.assertEqual(relido.canceladas(suporte.CNPJ_A), {'CH-1', 'CH-2'})
        self.assertEqual(json.loads((self.pasta / 'estado.json').read_text('utf-8'))['canceladas'][suporte.CNPJ_A],
                         ['CH-1', 'CH-2'])

    def test_ledger(self):
        est = robo.EstadoRobo(self.pasta)
        self.assertFalse(est.ja_escriturada(suporte.CNPJ_A, 'CH-1'))
        est.registrar_escriturada(suporte.CNPJ_A, 'CH-1')
        self.assertTrue(est.ja_escriturada(suporte.CNPJ_A, 'CH-1'))
        self.assertFalse(est.ja_escriturada(suporte.CNPJ_B, 'CH-1'))         # a chave é por empresa
        self.assertTrue(robo.EstadoRobo(self.pasta).ja_escriturada(suporte.CNPJ_A, 'CH-1'))

    def test_gravacao_atomica(self):
        est = robo.EstadoRobo(self.pasta)
        est.registrar_escriturada(suporte.CNPJ_A, 'chave com acentuação é mantida')
        self.assertFalse((self.pasta / 'estado.tmp').exists())                # o temporário foi renomeado
        texto = (self.pasta / 'estado.json').read_text('utf-8')
        self.assertIn('acentuação', texto)                                    # ensure_ascii=False
        dados = json.loads(texto)
        self.assertEqual(dados['ledger'][suporte.CNPJ_A], ['chave com acentuação é mantida'])
        self.assertEqual(dados['nsu'], {})

    def test_arquivar_e_arquivadas(self):
        est = robo.EstadoRobo(self.pasta)
        outra = robo.Competencia(2026, 8)
        n = nota('77', comp=outra, chave='NFS000/77')                          # a barra não pode ir para o nome
        est.arquivar(suporte.CNPJ_A, n)
        arquivo = self.pasta / 'arquivo' / suporte.CNPJ_A / '08-2026' / 'NFS000 77.xml'
        self.assertTrue(arquivo.exists(), list((self.pasta / 'arquivo').rglob('*')))
        self.assertEqual(arquivo.read_text('utf-8'), n.xml)
        self.assertEqual(est.arquivadas(suporte.CNPJ_A, outra), [n.xml])
        self.assertEqual(est.arquivadas(suporte.CNPJ_A, COMP), [])            # outra competência: nada
        self.assertEqual(est.arquivadas(suporte.CNPJ_B, outra), [])           # outro CNPJ: nada

    def test_arquivar_sem_competencia_nao_grava(self):
        est = robo.EstadoRobo(self.pasta)
        n = nota('1')
        n.competencia = None
        est.arquivar(suporte.CNPJ_A, n)
        self.assertFalse((self.pasta / 'arquivo').exists())


class TestPastaDaCompetencia(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cliente = Path(self._tmp.name) / '100 - Empresa Exemplo A Ltda'

    def tearDown(self):
        self._tmp.cleanup()

    def test_cria_quando_nao_existe(self):
        p = robo.pasta_da_competencia(self.cliente, COMP)
        self.assertEqual(p, self.cliente / 'NFE' / '2026' / '09-2026')
        self.assertTrue(p.is_dir())

    def test_reaproveita_a_pasta_feita_a_mao(self):
        for existente in ('09.2026', '092026', '09 2026', '9-2026'):
            with self.subTest(existente=existente):
                base = self.cliente / existente / 'NFE' / '2026'
                (base / existente).mkdir(parents=True)
                (base / '08-2026').mkdir()                                     # outro mês não confunde
                p = robo.pasta_da_competencia(self.cliente / existente, COMP)
                self.assertEqual(p, base / existente)
                self.assertFalse((base / '09-2026').exists())                 # não nasce uma segunda pasta
                self.assertEqual(sorted(x.name for x in base.iterdir()), sorted(['08-2026', existente]))

    def test_arquivo_com_nome_de_mes_nao_vale(self):
        base = self.cliente / 'NFE' / '2026'
        base.mkdir(parents=True)
        (base / '09.2026').write_text('não sou pasta', 'utf-8')
        self.assertEqual(robo.pasta_da_competencia(self.cliente, COMP), base / '09-2026')


class TestSalvarXmls(unittest.TestCase):
    def test_pastas_por_fonte_e_situacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            autorizada = nota('10', fonte='SP', nome='Prestador: Exemplo/1')
            cancelada = nota('11', fonte='Nacional', cancelada=True)
            prestada = nota('12', fonte='Nacional', papel='prestada', tomador_nome='Cliente Exemplo/2')
            sem_nome = nota('13', fonte='SP', papel='prestada', tomador_nome='')     # tomador sem nome: vai o CNPJ
            robo.salvar_xmls([autorizada, cancelada, prestada, sem_nome], pasta)
            a = pasta / 'Tomados' / 'Tomados SP' / 'Autorizadas' / 'Prestador Exemplo 1 NF 10.xml'
            c = pasta / 'Tomados' / 'Tomados Portal Nacional' / 'Canceladas' / 'Prestador Exemplo 1 NF 11.xml'
            p = pasta / 'Prestados' / 'Prestados Portal Nacional' / 'Autorizadas' / 'Cliente Exemplo 2 NF 12.xml'
            s = pasta / 'Prestados' / 'Prestados SP' / 'Autorizadas' / f'{suporte.CNPJ_B} NF 13.xml'
            self.assertTrue(a.exists(), list(pasta.rglob('*')))
            self.assertTrue(c.exists())
            self.assertTrue(p.exists(), list(pasta.rglob('*')))                 # prestada: pasta própria, nome do tomador
            self.assertTrue(s.exists(), list(pasta.rglob('*')))
            self.assertEqual(a.read_text('utf-8'), autorizada.xml)
            tem_reportlab = importlib.util.find_spec('reportlab') is not None
            self.assertEqual(a.with_suffix('.pdf').exists(), tem_reportlab)    # espelho só com reportlab


class _SenhaFixa(robo.SenhaProvider):
    def senha(self, cnpj):
        return 'x'


class _NacionalPorRodada:
    """Devolve, a cada chamada, a próxima lista de documentos (como se fossem NSUs novos chegando)."""

    def __init__(self, rodadas):
        self.rodadas = list(rodadas)

    def distribuir(self, cert, senha, ultimo_nsu):
        docs = self.rodadas.pop(0) if self.rodadas else []
        return docs, max([ultimo_nsu] + [d['nsu'] for d in docs])


class TestCancelamentoDeNotaArquivada(unittest.TestCase):
    """O evento de cancelamento chega UMA vez pelo NSU. Se naquela rodada só se pediram as tomadas, a prestada vai
    para o arquivo e o evento passa junto — na rodada das prestadas ela tem que sair cancelada mesmo assim."""

    def test_cancelamento_sobrevive_ao_arquivo(self):
        try:
            from . import test_leitura_xml as tl
        except ImportError:
            import test_leitura_xml as tl
        with tempfile.TemporaryDirectory() as tmp:
            estado = robo.EstadoRobo(Path(tmp) / 'estado')
            emp = suporte.empresa()
            evento = f'<pedRegEvento><infPedReg><chNFSe>{tl.CHAVE_PRESTADA}</chNFSe></infPedReg></pedRegEvento>'
            fonte = _NacionalPorRodada([[{'nsu': 1, 'chave': tl.CHAVE_PRESTADA, 'tipo': 'NFSE', 'xml': tl.XML_PRESTADA},
                                         {'nsu': 2, 'chave': tl.CHAVE_PRESTADA, 'tipo': 'EVENTO', 'xml': evento}]])
            fontes = {'Nacional': fonte}
            so_tomadas = robo.extrair_empresa(emp, COMP, object(), _SenhaFixa(), estado, fontes, papeis=['tomada'])
            self.assertEqual(so_tomadas, [])                                   # a prestada foi para o arquivo
            self.assertEqual(estado.ultimo_nsu(suporte.CNPJ_A), 2)
            self.assertEqual(estado.canceladas(suporte.CNPJ_A), {tl.CHAVE_PRESTADA})
            # rodada seguinte, agora pelas prestadas: nenhum NSU novo, a nota vem do arquivo — e cancelada
            prestadas = robo.extrair_empresa(emp, COMP, object(), _SenhaFixa(), robo.EstadoRobo(Path(tmp) / 'estado'),
                                             fontes, papeis=['prestada'])
            self.assertEqual([(n.numero, n.papel, n.cancelada) for n in prestadas], [('501', 'prestada', True)])


if __name__ == '__main__':
    unittest.main()
