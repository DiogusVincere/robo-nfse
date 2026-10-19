# -*- coding: utf-8 -*-
"""Seção 10 (escrituração com travas, sessão e ledger) sobre o PortalSimulado, seção 11 (exportação) e o
orquestrador da seção 13 (executar) — tudo em memória e em pastas temporárias."""
import random
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


def portal_sem_queda() -> robo.PortalSimulado:
    p = robo.PortalSimulado(random.Random(0))
    p.rnd = suporte.SemQueda()
    return p


class PortalQueCaiUmaVez(robo.PortalSimulado):
    """Derruba a sessão na primeira tentativa de preencher a nota 1002 — e só nela."""

    def __init__(self):
        super().__init__(random.Random(0))
        self.rnd = suporte.SemQueda()
        self.sessoes, self.derrubou = 0, False

    def abrir_sessao(self, empresa):
        self.sessoes += 1
        super().abrir_sessao(empresa)

    def preencher(self, empresa, nota):
        if nota.numero == '1002' and not self.derrubou:
            self.derrubou = True
            raise robo.SessaoPerdida()
        return super().preencher(empresa, nota)


class PortalQueSempreCai(PortalQueCaiUmaVez):
    def preencher(self, empresa, nota):
        raise robo.SessaoPerdida()


class PortalQueNaoConfirma(robo.PortalSimulado):
    """Grava, devolve o comprovante, mas a consulta posterior não lista a nota."""

    def __init__(self):
        super().__init__(random.Random(0))
        self.rnd = suporte.SemQueda()

    def gravar(self):
        self.formulario = None
        return b'%PDF-1.4\n% comprovante\n'


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.cfg = robo.Config(pasta_saida=self.raiz, pasta_estado=self.raiz / '_estado', pausa_entre_empresas=0)
        self.estado = robo.EstadoRobo(self.cfg.pasta_estado)
        self.empresa = suporte.empresa('100')
        self.pasta_comp = self.raiz / '100' / 'NFE' / '2026' / '09-2026'
        self.pasta_comp.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def escriturar(self, portal, notas, estado=None):
        res = robo.ResultadoEmpresa(self.empresa)
        robo.escriturar_empresa(portal, self.empresa, COMP, notas, self.pasta_comp, estado or self.estado, self.cfg, res)
        return res

    @staticmethod
    def situacoes(res):
        return {n.numero: s for n, s in res.notas}


class TestPortalSimulado(Base):
    def test_comportamento_basico(self):
        portal = portal_sem_queda()
        portal.abrir_sessao(self.empresa)
        self.assertEqual(portal.escrituradas(self.empresa, COMP), set())
        n = nota('4521', valor=1000.0, aliquota=2.0)
        previa = portal.preencher(self.empresa, n)
        self.assertEqual((previa.numero_documento, previa.iss_calculado), ('4521', 20.0))
        pdf = portal.gravar()
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(portal.escrituradas(self.empresa, COMP), {n.identidade})
        self.assertEqual(portal.escrituradas(self.empresa, robo.Competencia(2026, 8)), set())
        portal.preencher(self.empresa, nota('1'))
        portal.descartar()
        self.assertIsNone(portal.formulario)
        self.assertTrue(portal.emitir_guia_iss_retido(self.empresa, COMP).startswith(b'%PDF'))
        xmls, mapa = portal.exportar_xml_tomados(self.empresa, COMP)
        self.assertEqual(len(xmls), 1)
        self.assertEqual(mapa, {'1': '4521'})

    def test_defeito_de_proposito_na_setima_nota(self):
        portal = portal_sem_queda()
        for i in range(1, 8):
            previa = portal.preencher(self.empresa, nota(str(i), valor=1000.0, aliquota=2.0))
            self.assertEqual(previa.iss_calculado, 50.0 if i == 7 else 20.0)   # 5% em 1 de cada 7


class TestEscriturarEmpresa(Base):
    def test_travas_comprovantes_ledger_e_guia(self):
        notas = suporte.notas_fora(8, aliquota=2.0, valor=1000.0)
        notas[0].iss_retido = True
        res = self.escriturar(portal_sem_queda(), notas)
        sit = self.situacoes(res)
        self.assertEqual(res.escrituradas, 7)
        self.assertEqual(res.ja_escrituradas, 0)
        self.assertTrue(sit['1007'].startswith('NÃO escriturada: ISS do portal R$ 50.00'), sit['1007'])
        self.assertEqual([s for n, s in sit.items() if n != '1007'], ['escriturada'] * 7)
        self.assertEqual(len(res.erros), 1)
        self.assertIn('nota 1007', res.erros[0])
        pdfs = sorted(p.name for p in (self.pasta_comp / 'Tomados' / 'Notas Escrituradas').glob('*.pdf'))
        self.assertEqual(len(pdfs), 7)
        self.assertIn('Prestador Exemplo 1 NF 1001.pdf', pdfs)
        self.assertNotIn('Prestador Exemplo 1 NF 1007.pdf', pdfs)              # barrada: sem comprovante
        for n in notas:
            self.assertEqual(self.estado.ja_escriturada(self.empresa.cnpj, n.chave), n.numero != '1007')
        self.assertTrue(res.guia_emitida)                                      # havia ISS retido
        self.assertTrue((self.pasta_comp / 'Tomados' / 'Guia ISS retido 09-2026.pdf').exists())

    def test_sem_iss_retido_nao_emite_guia(self):
        res = self.escriturar(portal_sem_queda(), suporte.notas_fora(2, retido=False))
        self.assertFalse(res.guia_emitida)
        self.assertFalse((self.pasta_comp / 'Tomados' / 'Guia ISS retido 09-2026.pdf').exists())

    def test_ledger_impede_duplicar_na_segunda_chamada(self):
        notas = suporte.notas_fora(8, aliquota=2.0, valor=1000.0)
        primeira = self.escriturar(portal_sem_queda(), notas)
        self.assertEqual((primeira.escrituradas, primeira.ja_escrituradas), (7, 0))
        # portal NOVO (memória vazia, como um portal que não listasse nada) + mesmo estado: o ledger segura
        segunda = self.escriturar(portal_sem_queda(), notas)
        self.assertEqual(segunda.ja_escrituradas, 7)
        self.assertEqual(segunda.escrituradas, 1)                              # só a 1007, barrada antes, passa agora
        self.assertEqual(self.situacoes(segunda)['1007'], 'escriturada')
        terceira = self.escriturar(portal_sem_queda(), notas)
        self.assertEqual((terceira.escrituradas, terceira.ja_escrituradas), (0, 8))
        self.assertEqual(terceira.erros, [])

    def test_consulta_anti_duplicidade_no_portal(self):
        portal = portal_sem_queda()
        notas = suporte.notas_fora(3)
        self.escriturar(portal, notas)
        # MESMO portal (já lista as notas) + estado NOVO (sem ledger): a consulta anti-duplicidade segura
        outro_estado = robo.EstadoRobo(self.raiz / '_estado2')
        res = self.escriturar(portal, notas, estado=outro_estado)
        self.assertEqual((res.escrituradas, res.ja_escrituradas), (0, 3))
        self.assertEqual(set(self.situacoes(res).values()), {'já escriturada'})

    def test_sessao_perdida_e_renovada_e_a_nota_refeita(self):
        portal = PortalQueCaiUmaVez()
        with self.assertLogs('nfse', 'WARNING') as logs:
            res = self.escriturar(portal, suporte.notas_fora(3))
        self.assertEqual(portal.sessoes, 2)                                    # a inicial + a renovação
        self.assertEqual(res.escrituradas, 3)
        self.assertEqual(res.erros, [])
        self.assertTrue(any('sessão caiu' in m and '1002' in m for m in logs.output))

    def test_sessao_que_nunca_volta_vira_pendencia(self):
        portal = PortalQueSempreCai()
        with self.assertLogs('nfse', 'WARNING'):
            res = self.escriturar(portal, suporte.notas_fora(1))
        self.assertEqual(portal.sessoes, 4)                                    # 1 + 3 tentativas
        self.assertEqual(res.escrituradas, 0)
        self.assertEqual(self.situacoes(res)['1001'], 'erro: sessão')
        self.assertIn('não manteve a sessão', res.erros[0])
        self.assertFalse(self.estado.ja_escriturada(self.empresa.cnpj, 'CHAVE-1001'))

    def test_gravada_que_o_portal_nao_lista_vira_aviso(self):
        res = self.escriturar(PortalQueNaoConfirma(), suporte.notas_fora(2))
        self.assertEqual(res.escrituradas, 2)
        self.assertTrue(any('ainda não lista' in e for e in res.erros), res.erros)


class TestExportacao(Base):
    def test_exporta_renumerando(self):
        portal = portal_sem_queda()
        notas = suporte.notas_fora(2)
        self.escriturar(portal, notas)
        qtd = robo.exportar_para_sistema_contabil(portal, self.empresa, COMP, self.pasta_comp)
        self.assertEqual(qtd, 2)
        destino = self.pasta_comp / 'Tomados' / 'Importação XML Tomados'
        arquivos = sorted(p.name for p in destino.glob('*.xml'))
        self.assertEqual(arquivos, ['tomados_09-2026_001.xml', 'tomados_09-2026_002.xml'])
        from lxml import etree
        numeros = [robo.local(etree.fromstring((destino / a).read_bytes()), 'Numero') for a in arquivos]
        self.assertEqual(numeros, ['1001', '1002'])                            # o nº real, não o sequencial


class TestExecutar(Base):
    def test_sem_portal_lista_o_que_escriturar(self):
        com_retencao = robo.Retencoes(inss=110.0, irrf=15.0, csrf=46.5, csrf_quais='PIS+COFINS+CSLL')
        notas = [nota('1', municipio=suporte.OUTRO_MUNICIPIO), nota('2', municipio=suporte.MUNICIPIO),
                 nota('3', cancelada=True),
                 # prestadas: não se escrituram; o que importa é o que o cliente reteve
                 nota('4', papel='prestada', tomador_nome='Cliente Exemplo 1', retencoes=com_retencao),
                 nota('5', papel='prestada', tomador_nome='Cliente Exemplo 2', fonte='SP'),
                 nota('5', papel='prestada', tomador_nome='Cliente Exemplo 2', fonte='Nacional'),   # a mesma pelas 2 fontes
                 nota('6', papel='prestada', cancelada=True)]
        relatorios = robo.executar(self.cfg, COMP, [self.empresa], robo.SenhaDoAmbiente(), {}, None, {},
                                   extrator=lambda e: notas)
        self.assertEqual(len(relatorios), 1)
        self.assertEqual(relatorios[0].name, 'Analista 1 09-2026.xlsx')
        empresas, detalhe = suporte.ler_relatorio(relatorios[0])
        self.assertEqual(empresas['100']['Extraídas'], 7)
        self.assertEqual(empresas['100']['Tomadas'], 3)
        self.assertEqual(empresas['100']['Prestadas'], 3)                       # a 5 deduplicada
        self.assertEqual(empresas['100']['Fora do município'], 1)
        self.assertEqual(empresas['100']['Escrituradas agora'], 0)
        self.assertEqual(empresas['100']['Retido nas prestadas'], 171.5)
        self.assertEqual(empresas['100']['Retido nas tomadas'], 0)
        sit = {d['Nº']: d['Situação'] for d in detalhe}
        self.assertEqual(sit, {'1': 'fora do município — escriturar no portal do tomador',
                               '2': 'do município (não se declara)', '3': 'cancelada',
                               '4': 'prestada — com retenção', '5': 'prestada', '6': 'prestada cancelada'})
        papeis = {d['Nº']: d['Papel'] for d in detalhe}
        self.assertEqual(papeis, {'1': 'tomada', '2': 'tomada', '3': 'tomada', '4': 'prestada', '5': 'prestada', '6': 'prestada'})
        self.assertEqual([d['Fonte'] for d in detalhe if d['Nº'] == '5'], ['Nacional'])   # a Nacional é a que fica
        base = self.raiz / '100 - Empresa Exemplo 100 Ltda' / 'NFE' / '2026' / '09-2026'
        self.assertTrue((base / 'Tomados' / 'Tomados Portal Nacional' / 'Autorizadas' / 'Prestador Exemplo 1 NF 1.xml').exists())
        self.assertTrue((base / 'Prestados' / 'Prestados Portal Nacional' / 'Autorizadas' / 'Cliente Exemplo 1 NF 4.xml').exists())
        self.assertTrue((base / 'Prestados' / 'Prestados SP' / 'Autorizadas' / 'Cliente Exemplo 2 NF 5.xml').exists())

    def test_falha_isolada_e_um_relatorio_por_responsavel(self):
        e1, e2 = suporte.empresa('100', responsavel='Analista 1'), suporte.empresa('101', cnpj=suporte.CNPJ_B,
                                                                                     responsavel='Analista 2')

        def extrator(e):
            if e.codigo == '101':
                raise RuntimeError('sem certificado A1 válido')
            return suporte.notas_fora(2)

        with self.assertLogs('nfse', 'INFO'):
            relatorios = robo.executar(self.cfg, COMP, [e1, e2], robo.SenhaDoAmbiente(), {}, portal_sem_queda(),
                                       {}, extrator=extrator)
        self.assertEqual(sorted(r.name for r in relatorios), ['Analista 1 09-2026.xlsx', 'Analista 2 09-2026.xlsx'])
        empresas, _ = suporte.ler_relatorios(self.raiz)
        self.assertEqual(empresas['100']['Escrituradas agora'], 2)             # a primeira seguiu normalmente
        self.assertEqual(empresas['101']['Extraídas'], 0)
        self.assertIn('RuntimeError: sem certificado A1 válido', empresas['101']['Pendências'])

    def test_empresa_de_outro_municipio_nao_escritura_neste_portal(self):
        e = suporte.empresa('104', municipio='3550308')
        robo.executar(self.cfg, COMP, [e], robo.SenhaDoAmbiente(), {}, portal_sem_queda(), {},
                      extrator=lambda e: suporte.notas_fora(2, municipio='4106902'))
        empresas, detalhe = suporte.ler_relatorios(self.raiz)
        self.assertEqual(empresas['104']['Fora do município'], 2)
        self.assertEqual(empresas['104']['Escrituradas agora'], 0)
        self.assertTrue(all(d['Situação'].startswith('fora do município') for d in detalhe))


if __name__ == '__main__':
    unittest.main()
