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
            robo.salvar_xmls([autorizada, cancelada], pasta)
            a = pasta / 'Tomados' / 'Tomados SP' / 'Autorizadas' / 'Prestador Exemplo 1 NF 10.xml'
            c = pasta / 'Tomados' / 'Tomados Portal Nacional' / 'Canceladas' / 'Prestador Exemplo 1 NF 11.xml'
            self.assertTrue(a.exists(), list(pasta.rglob('*')))
            self.assertTrue(c.exists())
            self.assertEqual(a.read_text('utf-8'), autorizada.xml)
            tem_reportlab = importlib.util.find_spec('reportlab') is not None
            self.assertEqual(a.with_suffix('.pdf').exists(), tem_reportlab)    # espelho só com reportlab


if __name__ == '__main__':
    unittest.main()
