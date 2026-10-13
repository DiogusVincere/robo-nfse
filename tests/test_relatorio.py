# -*- coding: utf-8 -*-
"""Seção 12 (relatório e e-mail), seção 8 (espelho em PDF) e o Progresso da seção 13."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import suporte
except ImportError:
    import suporte

robo = suporte.robo
nota = suporte.nota
COMP = suporte.COMP

CABECALHO_EMPRESAS = ['Código', 'Empresa', 'CNPJ', 'Extraídas', 'Fora do município', 'Escrituradas agora',
                      'Já escrituradas', 'Guia ISS', 'Pendências']
CABECALHO_NOTAS = ['Código', 'Fonte', 'Nº', 'Emissão', 'Prestador', 'CNPJ prestador', 'Município (IBGE)',
                   'Valor', 'Alíquota %', 'ISS', 'ISS retido', 'Situação']


class TestGerarRelatorio(unittest.TestCase):
    def test_duas_abas_com_resumo_e_detalhe(self):
        from openpyxl import load_workbook
        e1, e2 = suporte.empresa('100'), suporte.empresa('101', cnpj=suporte.CNPJ_B, municipio='3550308')
        r1 = robo.ResultadoEmpresa(e1, extraidas=3, fora_do_municipio=2, escrituradas=1, ja_escrituradas=1,
                                   guia_emitida=True, erros=['nota 3: ISS do portal R$ 50.00 ≠ valor × alíquota R$ 20.00'])
        r1.notas = [(nota('1', retido=True), 'escriturada'), (nota('2'), 'já escriturada'),
                    (nota('3', fonte='SP'), 'NÃO escriturada: ISS do portal R$ 50.00 ≠ valor × alíquota R$ 20.00')]
        r2 = robo.ResultadoEmpresa(e2, erros=['RuntimeError: sem certificado A1 válido'])
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / '_relatorios' / 'Analista 1 09-2026.xlsx'     # a pasta ainda não existe
            devolvido = robo.gerar_relatorio([r1, r2], COMP, destino)
            self.assertEqual(devolvido, destino)
            self.assertTrue(destino.exists())
            wb = load_workbook(destino)
            self.assertEqual(wb.sheetnames, ['Empresas', 'Notas'])
            emp = list(wb['Empresas'].iter_rows(values_only=True))
            det = list(wb['Notas'].iter_rows(values_only=True))
            self.assertEqual(list(emp[0]), CABECALHO_EMPRESAS)
            self.assertEqual(list(det[0]), CABECALHO_NOTAS)
            self.assertEqual(len(emp), 3)                                      # cabeçalho + 2 empresas
            self.assertEqual(list(emp[1]), ['100', e1.razao, e1.cnpj, 3, 2, 1, 1, 'sim',
                                            'nota 3: ISS do portal R$ 50.00 ≠ valor × alíquota R$ 20.00'])
            self.assertEqual(list(emp[2])[:3], ['101', e2.razao, e2.cnpj])
            self.assertIn(emp[2][7], ('', None))                               # sem guia (célula vazia volta None)
            self.assertEqual(emp[2][8], 'RuntimeError: sem certificado A1 válido')
            self.assertEqual(len(det), 4)                                      # cabeçalho + 3 notas
            self.assertEqual(list(det[1]), ['100', 'Nacional', '1', '10/09/2026', 'Prestador Exemplo 1',
                                            suporte.CNPJ_PRESTADOR, suporte.OUTRO_MUNICIPIO, 1000.0, 2.0, 20.0,
                                            'sim', 'escriturada'])
            self.assertEqual(det[3][1], 'SP')
            self.assertTrue(det[3][11].startswith('NÃO escriturada'))
            self.assertTrue(wb['Empresas']['A1'].font.bold)                    # cabeçalho formatado
            self.assertGreaterEqual(wb['Notas'].column_dimensions['L'].width, 10)
            wb.close()

    def test_sem_resultados_gera_so_cabecalhos(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as tmp:
            arq = robo.gerar_relatorio([], COMP, Path(tmp) / 'vazio.xlsx')
            wb = load_workbook(arq)
            self.assertEqual(wb['Empresas'].max_row, 1)
            self.assertEqual(wb['Notas'].max_row, 1)
            wb.close()


class TestEspelhoPdf(unittest.TestCase):
    def test_segue_sem_reportlab_e_gera_com_ele(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / 'espelho.pdf'
            ok = robo.gerar_espelho_pdf(nota('1'), destino)
            tem_reportlab = importlib.util.find_spec('reportlab') is not None
            self.assertEqual(ok, tem_reportlab)
            self.assertEqual(destino.exists(), tem_reportlab)
            if tem_reportlab:
                self.assertTrue(destino.read_bytes().startswith(b'%PDF'))

    def test_sem_reportlab_mesmo_que_ele_exista(self):
        """Força o ImportError para garantir o caminho 'espelho é conveniência'."""
        with mock.patch.dict('sys.modules', {'reportlab': None, 'reportlab.lib.pagesizes': None,
                                             'reportlab.pdfgen': None}):
            with tempfile.TemporaryDirectory() as tmp:
                destino = Path(tmp) / 'espelho.pdf'
                self.assertFalse(robo.gerar_espelho_pdf(nota('1'), destino))
                self.assertFalse(destino.exists())


class TestEnviarPorEmail(unittest.TestCase):
    def test_sem_configuracao_nao_envia(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {'NFSE_SMTP_SENHA': ''}):
            anexo = Path(tmp) / 'r.xlsx'
            anexo.write_bytes(b'x')
            cfg = robo.Config(pasta_saida=Path(tmp), pasta_estado=Path(tmp), smtp_host='', smtp_usuario='')
            with self.assertLogs('nfse_tomados', 'INFO') as logs:
                self.assertFalse(robo.enviar_por_email(cfg, 'alguem@exemplo.test', anexo, COMP))
            self.assertTrue(any('não configurado' in m for m in logs.output))
            # servidor e usuário preenchidos, mas sem a senha no ambiente: também não tenta
            cfg = robo.Config(pasta_saida=Path(tmp), pasta_estado=Path(tmp),
                              smtp_host='smtp.exemplo.test', smtp_usuario='robo@exemplo.test')
            self.assertFalse(robo.enviar_por_email(cfg, 'alguem@exemplo.test', anexo, COMP))
            # sem destinatário, idem
            with mock.patch.dict(os.environ, {'NFSE_SMTP_SENHA': 'x'}):
                self.assertFalse(robo.enviar_por_email(cfg, '', anexo, COMP))


class TestProgresso(unittest.TestCase):
    def test_conta_e_registra(self):
        p = robo.Progresso(2)
        with self.assertLogs('nfse_tomados', 'INFO') as logs:
            p.avanca('primeira')
            p.avanca('segunda')
        self.assertEqual(p.feitos, 2)
        self.assertIn('[1/2] primeira', logs.output[0])
        self.assertIn('[2/2] segunda', logs.output[1])
        self.assertIn('faltam ~0s', logs.output[1])


if __name__ == '__main__':
    unittest.main()
