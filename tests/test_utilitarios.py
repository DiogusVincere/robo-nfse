# -*- coding: utf-8 -*-
"""Seção 1 (utilitários) e o gerador de CNPJ fictício da seção 14."""
import datetime as dt
import random
import unittest

try:
    from . import suporte
except ImportError:
    import suporte

from lxml import etree

robo = suporte.robo


class TestCompetencia(unittest.TestCase):
    def test_de_texto_aceita_os_tres_formatos(self):
        esperado = robo.Competencia(2026, 9)
        self.assertEqual(robo.Competencia.de_texto('09/2026'), esperado)
        self.assertEqual(robo.Competencia.de_texto('09-2026'), esperado)
        self.assertEqual(robo.Competencia.de_texto('2026-09'), esperado)
        self.assertEqual(robo.Competencia.de_texto(' 9/2026 '), esperado)      # mês sem zero e com espaços

    def test_de_texto_rejeita_o_resto(self):
        for ruim in ('092026', '2026/09', 'setembro', '', '13-2026x'):
            with self.subTest(ruim=ruim), self.assertRaises(ValueError):
                robo.Competencia.de_texto(ruim)

    def test_anterior_a(self):
        self.assertEqual(robo.Competencia.anterior_a(dt.date(2026, 10, 13)), robo.Competencia(2026, 9))
        self.assertEqual(robo.Competencia.anterior_a(dt.date(2026, 1, 1)), robo.Competencia(2025, 12))  # vira o ano

    def test_inicio_e_fim(self):
        self.assertEqual(robo.Competencia(2026, 2).fim, dt.date(2026, 2, 28))
        self.assertEqual(robo.Competencia(2024, 2).fim, dt.date(2024, 2, 29))          # bissexto
        self.assertEqual(robo.Competencia(2100, 2).fim, dt.date(2100, 2, 28))          # século não bissexto
        self.assertEqual(robo.Competencia(2026, 12).fim, dt.date(2026, 12, 31))
        self.assertEqual(robo.Competencia(2026, 9).inicio, dt.date(2026, 9, 1))

    def test_texto_pasta_e_ordem(self):
        c = robo.Competencia(2026, 9)
        self.assertEqual(str(c), '09/2026')
        self.assertEqual(c.pasta, '09-2026')
        self.assertLess(robo.Competencia(2026, 9), robo.Competencia(2026, 10))
        self.assertLess(robo.Competencia(2025, 12), robo.Competencia(2026, 1))
        self.assertEqual(len({robo.Competencia(2026, 9), robo.Competencia.de_texto('09/2026')}), 1)  # hashável


class TestParaFloat(unittest.TestCase):
    def test_formatos(self):
        casos = {'1.234,56': 1234.56, '1234.56': 1234.56, '12,5': 12.5, '0.05': 0.05, ' 7 ': 7.0,
                 '1.000': 1.0, 1500: 1500.0, '2.5': 2.5}
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertAlmostEqual(robo.para_float(entrada), esperado)

    def test_vazio_e_lixo_viram_zero(self):
        for v in (None, '', 'abc', 'R$'):
            with self.subTest(v=v):
                self.assertEqual(robo.para_float(v), 0.0)


class TestNomeSeguro(unittest.TestCase):
    def test_tira_o_que_o_windows_nao_aceita(self):
        self.assertEqual(robo.nome_seguro('Prestador: A/B?'), 'Prestador A B')
        self.assertEqual(robo.nome_seguro('nome<>:"|*\\fim'), 'nome fim')
        self.assertEqual(robo.nome_seguro('Empresa S.A.'), 'Empresa S.A')             # ponto final não fica
        self.assertEqual(robo.nome_seguro('a\x00b\x1fc'), 'a b c')                      # caracteres de controle

    def test_espacos_limite_e_vazio(self):
        self.assertEqual(robo.nome_seguro('  muitos    espaços  '), 'muitos espaços')
        self.assertEqual(robo.nome_seguro('abcdefghij', limite=4), 'abcd')
        self.assertEqual(robo.nome_seguro(''), 'sem_nome')
        self.assertEqual(robo.nome_seguro(None), 'sem_nome')
        self.assertEqual(robo.nome_seguro('???'), 'sem_nome')


class TestDigitosLocalGrupo(unittest.TestCase):
    def test_digitos(self):
        self.assertEqual(robo.digitos('12.345.678/0001-95'), '12345678000195')
        self.assertEqual(robo.digitos(None), '')
        self.assertEqual(robo.digitos(4521), '4521')

    def test_local_e_grupo_ignoram_namespace(self):
        raiz = etree.fromstring('<a xmlns="urn:x"><emit><CNPJ>  123  </CNPJ></emit><toma><CNPJ>456</CNPJ></toma></a>')
        self.assertEqual(robo.local(raiz, 'CNPJ'), '123')                             # o primeiro, e sem espaços
        self.assertIsNone(robo.local(raiz, 'inexistente'))
        toma = robo.grupo(raiz, 'tomador', 'toma')
        self.assertEqual(robo.local(toma, 'CNPJ'), '456')
        self.assertIsNone(robo.grupo(raiz, 'prestador'))
        self.assertIsNone(robo.local(etree.fromstring('<a><b/></a>'), 'b'))             # elemento vazio → None


class TestCnpjFicticio(unittest.TestCase):
    def test_gera_cnpj_valido_e_reproduzivel(self):
        rnd = random.Random(7)
        gerados = [robo.cnpj_ficticio(rnd) for _ in range(50)]
        for c in gerados:
            self.assertEqual(len(c), 14)
            self.assertTrue(c.isdigit())
            self.assertEqual(c[8:12], '0001')                                          # matriz
            self.assertTrue(suporte.cnpj_valido(c), c)
        rnd2 = random.Random(7)
        self.assertEqual(gerados, [robo.cnpj_ficticio(rnd2) for _ in range(50)])      # mesma semente, mesma lista
        self.assertEqual(len(set(gerados)), 50)                                       # e sem repetição
        self.assertFalse(suporte.cnpj_valido('12345678000100'))                        # o validador do teste funciona


if __name__ == '__main__':
    unittest.main()
