# -*- coding: utf-8 -*-
"""Seção 9 (classificação) e as travas da seção 10 (conferir_antes_de_gravar)."""
import unittest

try:
    from . import suporte
except ImportError:
    import suporte

robo = suporte.robo
nota = suporte.nota


class TestClassificar(unittest.TestCase):
    def test_separa_do_municipio_fora_e_canceladas(self):
        notas = [nota('1', municipio=suporte.OUTRO_MUNICIPIO),
                 nota('2', municipio=suporte.MUNICIPIO),
                 nota('3', municipio=suporte.MUNICIPIO, cancelada=True),      # cancelada ganha de "do município"
                 nota('4', municipio='4106902', cancelada=True)]
        g = robo.classificar(notas, suporte.MUNICIPIO)
        self.assertEqual([n.numero for n in g['fora']], ['1'])
        self.assertEqual([n.numero for n in g['do_municipio']], ['2'])
        self.assertEqual([n.numero for n in g['canceladas']], ['3', '4'])

    def test_deduplica_entre_fontes_preferindo_a_nacional(self):
        sp = nota('0045', fonte='SP', valor=1200.0)
        nac = nota('45', fonte='Nacional', valor=1200.0)                      # a mesma nota: zeros à esquerda não contam
        outra = nota('45', fonte='SP', valor=1200.01)                         # valor diferente = outra nota
        g = robo.classificar([sp, nac, outra], suporte.MUNICIPIO)             # SP vem primeiro na lista…
        self.assertEqual(len(g['fora']), 2)
        self.assertEqual(g['fora'][0].fonte, 'Nacional')                      # …mas a Nacional é a que fica
        self.assertEqual(g['fora'][0].numero, '45')
        self.assertIn(outra, g['fora'])
        self.assertEqual(sum(len(v) for v in g.values()), 2)

    def test_lista_vazia(self):
        self.assertEqual(robo.classificar([], suporte.MUNICIPIO), {'do_municipio': [], 'fora': [], 'canceladas': []})


class TestConferirAntesDeGravar(unittest.TestCase):
    def setUp(self):
        self.nota = nota('4521', valor=1000.0, aliquota=2.0)                  # ISS esperado: R$ 20,00

    def test_numero_diferente_bloqueia(self):
        motivo = robo.conferir_antes_de_gravar(self.nota, robo.Previa('4522', 20.0), 0.01)
        self.assertIsNotNone(motivo)
        self.assertIn('4522', motivo)
        self.assertIn('4521', motivo)

    def test_zeros_a_esquerda_nao_bloqueiam(self):
        self.assertIsNone(robo.conferir_antes_de_gravar(self.nota, robo.Previa('0004521', 20.0), 0.01))

    def test_iss_fora_da_tolerancia_bloqueia(self):
        motivo = robo.conferir_antes_de_gravar(self.nota, robo.Previa('4521', 50.0), 0.01)   # alíquota padrão de 5%
        self.assertIsNotNone(motivo)
        self.assertIn('ISS', motivo)
        self.assertIn('50.00', motivo)
        self.assertIn('20.00', motivo)
        self.assertIsNotNone(robo.conferir_antes_de_gravar(self.nota, robo.Previa('4521', 20.02), 0.01))

    def test_dentro_da_tolerancia_passa(self):
        self.assertIsNone(robo.conferir_antes_de_gravar(self.nota, robo.Previa('4521', 20.0), 0.01))
        self.assertIsNone(robo.conferir_antes_de_gravar(self.nota, robo.Previa('4521', 20.005), 0.01))  # meio centavo
        self.assertIsNone(robo.conferir_antes_de_gravar(self.nota, robo.Previa('4521', 19.995), 0.01))

    def test_arredondamento_do_esperado(self):
        n = nota('1', valor=333.33, aliquota=3.0)                             # 9.9999 → 10.00
        self.assertIsNone(robo.conferir_antes_de_gravar(n, robo.Previa('1', 10.0), 0.01))


if __name__ == '__main__':
    unittest.main()
