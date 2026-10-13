# -*- coding: utf-8 -*-
"""Seção 14: a demonstração offline de ponta a ponta, rodada mais de uma vez na mesma pasta, e a linha de comando."""
import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import suporte
except ImportError:
    import suporte

robo = suporte.robo


class PortalDeterministico(robo.PortalSimulado):
    """O PortalSimulado da demonstração nasce com `random.Random()` sem semente (as quedas de sessão variam a cada
    execução). Aqui a semente é fixa, para o teste afirmar exatamente o que acontece em cada rodada.

    Com a semente 12: 3 quedas de sessão recuperadas e 3 notas barradas pela trava do ISS na 1ª rodada. Sem nenhuma
    queda, as notas que caem nas posições 7 e 14 do contador do portal são de alíquota 5% — igual à "padrão" do
    defeito — e a trava não teria o que barrar."""

    def __init__(self, rnd):
        super().__init__(random.Random(12))


def situacoes(notas):
    """{(código, nº): situação} da aba Notas."""
    return {(str(d['Código']), str(d['Nº'])): d['Situação'] for d in notas}


class TestDemonstracao(unittest.TestCase):
    def test_tres_execucoes_na_mesma_pasta(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(robo, 'PortalSimulado', PortalDeterministico):
            saida = Path(tmp) / 'demo'
            comp = robo.Competencia.anterior_a(robo.dt.date.today())

            # ---- 1ª execução: escritura, e a trava do ISS barra o "defeito" 1 em 7 do portal
            relatorios = robo.demonstracao(saida)
            self.assertEqual(sorted(r.name for r in relatorios),
                             [f'Analista 1 {comp.pasta}.xlsx', f'Analista 2 {comp.pasta}.xlsx'])
            self.assertTrue(all(r.exists() for r in relatorios))
            emp1, notas1 = suporte.ler_relatorios(saida)
            self.assertEqual(sorted(emp1), ['100', '101', '102', '103', '104', '105'])
            escrituradas1 = sum(e['Escrituradas agora'] for e in emp1.values())
            self.assertGreater(escrituradas1, 0)
            self.assertEqual(sum(e['Já escrituradas'] for e in emp1.values()), 0)
            barradas1 = {k for k, s in situacoes(notas1).items() if s.startswith('NÃO escriturada')}
            self.assertGreater(len(barradas1), 0)                                 # a trava trabalhou
            self.assertTrue(all('ISS do portal' in emp1[c]['Pendências'] for c, _ in barradas1))
            # empresas de outro município (104 e 105) não escrituram neste portal
            for cod in ('104', '105'):
                self.assertEqual(emp1[cod]['Escrituradas agora'], 0)
                self.assertTrue(any(s.startswith('fora do município') for (c, _), s in situacoes(notas1).items()
                                    if c == cod))
            gravadas1 = {k for k, s in situacoes(notas1).items() if s == 'escriturada'}
            self.assertEqual(len(gravadas1), escrituradas1)
            estado = json.loads((saida / '_estado' / 'estado.json').read_text('utf-8'))
            self.assertEqual(sum(len(v) for v in estado['ledger'].values()), escrituradas1)
            # pastas por empresa e comprovantes
            self.assertTrue((saida / '100 - Empresa Exemplo A Ltda' / 'NFE' / str(comp.ano) / comp.pasta / 'Tomados'
                             / 'Notas Escrituradas').is_dir())

            # ---- 2ª execução: nada do que foi gravado é gravado de novo; só o que foi barrado tem nova chance
            robo.demonstracao(saida)
            emp2, notas2 = suporte.ler_relatorios(saida)
            sit2 = situacoes(notas2)
            self.assertGreater(sum(e['Já escrituradas'] for e in emp2.values()), 0)
            for k in gravadas1:
                self.assertEqual(sit2[k], 'já escriturada', k)
            gravadas2 = {k for k, s in sit2.items() if s == 'escriturada'}
            self.assertEqual(gravadas2, barradas1)                                # exatamente as barradas antes
            self.assertEqual(sum(e['Escrituradas agora'] for e in emp2.values()), len(barradas1))
            self.assertEqual(sum(e['Já escrituradas'] for e in emp2.values()), escrituradas1)
            self.assertEqual(sum(e['Extraídas'] for e in emp2.values()), sum(e['Extraídas'] for e in emp1.values()))

            # ---- 3ª execução: tudo "já escriturada", zero gravações
            robo.demonstracao(saida)
            emp3, notas3 = suporte.ler_relatorios(saida)
            self.assertEqual(sum(e['Escrituradas agora'] for e in emp3.values()), 0)
            self.assertEqual(sum(e['Já escrituradas'] for e in emp3.values()), escrituradas1 + len(barradas1))
            self.assertEqual({s for s in situacoes(notas3).values() if 'escriturada' in s}, {'já escriturada'})
            self.assertTrue(all(not e['Pendências'] for e in emp3.values()), [e['Pendências'] for e in emp3.values()])

    def test_demonstracao_sem_semente_tambem_roda(self):
        """A função como ela é (quedas de sessão ao acaso): gera as pastas e os dois relatórios."""
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp)
            relatorios = robo.demonstracao(saida)
            self.assertEqual(len(relatorios), 2)
            emp, notas = suporte.ler_relatorios(saida)
            self.assertEqual(len(emp), 6)
            self.assertGreater(sum(e['Escrituradas agora'] for e in emp.values()), 0)
            self.assertTrue((saida / '_estado' / 'estado.json').exists())
            self.assertEqual(len(list(saida.glob('1?? - Empresa Exemplo ? Ltda'))), 6)


class TestLinhaDeComando(unittest.TestCase):
    def test_demo_pela_linha_de_comando(self):
        with tempfile.TemporaryDirectory() as tmp:
            # o basicConfig do main ligaria a saída de log no terminal para o resto da suíte
            with mock.patch.object(robo.logging, 'basicConfig'), self.assertLogs('nfse_tomados', 'INFO') as logs:
                robo.main(['--demo', '--saida', tmp])
            self.assertEqual(len(list((Path(tmp) / '_relatorios').glob('*.xlsx'))), 2)
            self.assertTrue(any('demonstração concluída' in m for m in logs.output))
            self.assertTrue(any('[6/6]' in m for m in logs.output))

    def test_sem_argumentos_explica_o_que_falta(self):
        erro = io.StringIO()
        with contextlib.redirect_stderr(erro), self.assertRaises(SystemExit) as cm:
            robo.main([])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn('--empresas', erro.getvalue())


class TestCarregarEmpresas(unittest.TestCase):
    def test_arquivo_de_exemplo(self):
        empresas = robo.carregar_empresas(suporte.RAIZ / 'exemplos' / 'empresas.exemplo.json')
        self.assertEqual(len(empresas), 6)
        self.assertEqual([e.codigo for e in empresas], ['100', '101', '102', '103', '104', '105'])
        for e in empresas:
            self.assertTrue(suporte.cnpj_valido(e.cnpj), e.cnpj)               # fictícios, mas com DV válido
            self.assertEqual(len(e.municipio_ibge), 7)
            self.assertIn(e.responsavel, ('Analista 1', 'Analista 2'))
            self.assertIsNone(e.pasta)
        self.assertEqual(len({e.cnpj for e in empresas}), 6)

    def test_ignora_campos_extras(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / 'e.json'
            arq.write_text(json.dumps([{'codigo': '1', 'razao': 'X', 'cnpj': suporte.CNPJ_A, 'municipio_ibge': '3509502',
                                        'responsavel': 'A', 'observacao': 'não é campo da Empresa'}]), 'utf-8')
            [e] = robo.carregar_empresas(arq)
            self.assertEqual((e.codigo, e.cnpj), ('1', suporte.CNPJ_A))


if __name__ == '__main__':
    unittest.main()
