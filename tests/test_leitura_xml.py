# -*- coding: utf-8 -*-
"""Seções 5 (partes puras dos clientes), 6 (XML → Nota, inclusive as RETENÇÕES) e 11 (renumeração) com XMLs
sintéticos mínimos."""
import base64
import dataclasses
import datetime as dt
import gzip
import unittest

try:
    from . import suporte
except ImportError:
    import suporte

from lxml import etree

robo = suporte.robo

XML_SP = f'''<?xml version="1.0" encoding="UTF-8"?>
<NFe xmlns="http://www.prefeitura.sp.gov.br/nfe">
  <ChaveNFe><InscricaoPrestador>12345678</InscricaoPrestador><NumeroNFe>4521</NumeroNFe>
    <CodigoVerificacao>ABCD1234</CodigoVerificacao></ChaveNFe>
  <DataEmissaoNFe>2026-09-15</DataEmissaoNFe>
  <StatusNFe>N</StatusNFe>
  <ValorServicos>1000.00</ValorServicos>
  <ValorISS>50.00</ValorISS>
  <AliquotaServicos>0.05</AliquotaServicos>
  <ISSRetido>true</ISSRetido>
  <CPFCNPJPrestador><CNPJ>{suporte.CNPJ_PRESTADOR}</CNPJ></CPFCNPJPrestador>
  <RazaoSocialPrestador>Prestador Exemplo 1</RazaoSocialPrestador>
  <EnderecoPrestador><Cidade>3304557</Cidade></EnderecoPrestador>
  <CPFCNPJTomador><CNPJ>{suporte.CNPJ_A}</CNPJ></CPFCNPJTomador>
  <RazaoSocialTomador>Empresa Exemplo A Ltda</RazaoSocialTomador>
  <EnderecoTomador><Cidade>3509502</Cidade></EnderecoTomador>
</NFe>'''

# a mesma nota com as retenções federais preenchidas (os campos do leiaute da Nota Paulistana)
XML_SP_RETENCOES = XML_SP.replace('<ISSRetido>true</ISSRetido>', '''<ISSRetido>true</ISSRetido>
  <ValorPIS>6.50</ValorPIS><ValorCOFINS>30.00</ValorCOFINS><ValorINSS>110.00</ValorINSS>
  <ValorIR>15.00</ValorIR><ValorCSLL>46.50</ValorCSLL>''')

CHAVE_NACIONAL = 'NFS' + '35503082' + '0' * 41 + '1'                # NFS + 50 dígitos

XML_NACIONAL = f'''<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.00">
  <infNFSe Id="{CHAVE_NACIONAL}">
    <cLocEmi>3304557</cLocEmi>
    <nNFSe>88</nNFSe>
    <dhProc>2026-09-30T23:59:00-03:00</dhProc>
    <emit><CNPJ>{suporte.CNPJ_PRESTADOR}</CNPJ><xNome>Prestador Exemplo 2</xNome>
      <enderNac><cMun>4106902</cMun></enderNac></emit>
    <valores><vBC>2500.00</vBC><pAliqAplic>3.00</pAliqAplic><vISSQN>75.00</vISSQN>
      <vTotalRet>75.00</vTotalRet><vLiq>2425.00</vLiq></valores>
    <DPS><infDPS Id="DPS000">
      <dhEmi>2026-10-01T08:00:00-03:00</dhEmi>
      <tpEmit>1</tpEmit>
      <prest><CNPJ>99999999999999</CNPJ></prest>
      <toma><CNPJ>{suporte.CNPJ_A}</CNPJ><xNome>Empresa Exemplo A Ltda</xNome>
        <end><endNac><cMun>3509502</cMun></endNac></end></toma>
      <valores><vServPrest><vServ>2500.00</vServ></vServPrest>
        <trib><tribMun><tribISSQN>1</tribISSQN><tpRetISSQN>2</tpRetISSQN><pAliq>3.00</pAliq></tribMun>__TRIBFED__</trib>
      </valores>
    </infDPS></DPS>
  </infNFSe>
</NFSe>'''.replace('__TRIBFED__', '')


def xml_nacional(trib_fed: str = '', tp_ret_iss: str = '2', v_total_ret: str = None, v_liq: str = None) -> str:
    """A nota nacional sintética com o grupo tribFed, o tipo de retenção do ISS e os totais que o teste quiser."""
    xml = XML_NACIONAL.replace('</tribMun>', '</tribMun>' + trib_fed).replace('<tpRetISSQN>2', f'<tpRetISSQN>{tp_ret_iss}')
    if v_total_ret is not None:
        xml = xml.replace('<vTotalRet>75.00</vTotalRet>', f'<vTotalRet>{v_total_ret}</vTotalRet>')
    if v_liq is not None:
        xml = xml.replace('<vLiq>2425.00</vLiq>', f'<vLiq>{v_liq}</vLiq>')
    return xml


def trib_fed(v_ret_cp='0', v_ret_irrf='0', v_ret_csll='0', codigo=None, v_pis='0', v_cofins='0') -> str:
    piscofins = (f'<piscofins><CST>01</CST><vPis>{v_pis}</vPis><vCofins>{v_cofins}</vCofins>'
                 f'<tpRetPisCofins>{codigo}</tpRetPisCofins></piscofins>') if codigo is not None else ''
    return f'<tribFed>{piscofins}<vRetCP>{v_ret_cp}</vRetCP><vRetIRRF>{v_ret_irrf}</vRetIRRF><vRetCSLL>{v_ret_csll}</vRetCSLL></tribFed>'


# uma nota que a empresa A PRESTOU (ela é o emitente; o tomador é a empresa B), com retenções federais pela NT 007
CHAVE_PRESTADA = CHAVE_NACIONAL[:-1] + '5'
XML_PRESTADA = f'''<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.00">
  <infNFSe Id="{CHAVE_PRESTADA}">
    <cLocEmi>3509502</cLocEmi>
    <nNFSe>501</nNFSe>
    <dhProc>2026-09-21T10:00:00-03:00</dhProc>
    <emit><CNPJ>{suporte.CNPJ_A}</CNPJ><xNome>EMPRESA EXEMPLO A LTDA</xNome><enderNac><cMun>3509502</cMun></enderNac></emit>
    <valores><vBC>1000.00</vBC><pAliqAplic>2.00</pAliqAplic><vISSQN>20.00</vISSQN>
      <vTotalRet>171.50</vTotalRet><vLiq>828.50</vLiq></valores>
    <DPS><infDPS Id="DPS001">
      <dhEmi>2026-09-21T09:00:00-03:00</dhEmi>
      <tpEmit>1</tpEmit>
      <prest><CNPJ>{suporte.CNPJ_A}</CNPJ></prest>
      <toma><CNPJ>{suporte.CNPJ_B}</CNPJ><xNome>Cliente Exemplo B</xNome><end><endNac><cMun>3550308</cMun></endNac></end></toma>
      <valores><vServPrest><vServ>1000.00</vServ></vServPrest>
        <trib><tribMun><tribISSQN>1</tribISSQN><tpRetISSQN>1</tpRetISSQN><pAliq>2.00</pAliq></tribMun>
          {trib_fed(v_ret_cp='110.00', v_ret_irrf='15.00', v_ret_csll='46.50', codigo='3')}</trib>
      </valores>
    </infDPS></DPS>
  </infNFSe>
</NFSe>'''


class TestNotaDeSP(unittest.TestCase):
    def test_campos(self):
        n = robo.nota_de_sp(XML_SP)
        self.assertEqual(n.fonte, 'SP')
        self.assertEqual(n.papel, 'tomada')                                # padrão: o que a empresa recebeu
        self.assertEqual(n.numero, '4521')
        self.assertEqual(n.chave, 'SP-4521-ABCD1234')
        self.assertEqual(n.emissao, dt.date(2026, 9, 15))
        self.assertEqual(n.competencia, robo.Competencia(2026, 9))
        self.assertEqual(n.prestador_cnpj, suporte.CNPJ_PRESTADOR)
        self.assertEqual(n.prestador_nome, 'Prestador Exemplo 1')
        self.assertEqual(n.prestador_municipio_ibge, '3304557')
        self.assertEqual(n.tomador_cnpj, suporte.CNPJ_A)
        self.assertEqual(n.tomador_nome, 'Empresa Exemplo A Ltda')
        self.assertEqual(n.tomador_municipio_ibge, '3509502')
        self.assertEqual(n.valor_servico, 1000.0)
        self.assertEqual(n.aliquota, 5.0)                                  # 0.05 → 5%
        self.assertEqual(n.valor_iss, 50.0)
        self.assertTrue(n.iss_retido)
        self.assertEqual((n.retencoes.iss, n.retencoes.iss_por), (50.0, 'tomador'))
        self.assertEqual(n.retencoes.total, 50.0)                          # só o ISS
        self.assertEqual(n.valor_liquido, 950.0)                           # SP não manda o líquido: valor − retenções
        self.assertFalse(n.cancelada)
        self.assertEqual(n.xml, XML_SP)                                    # o XML original fica na nota

    def test_papel_prestada(self):
        n = robo.nota_de_sp(XML_SP, 'prestada')
        self.assertEqual(n.papel, 'prestada')
        self.assertEqual(n.contraparte, 'Empresa Exemplo A Ltda')          # numa prestada, o outro lado é o tomador
        self.assertEqual(robo.nota_de_sp(XML_SP).contraparte, 'Prestador Exemplo 1')

    def test_variantes(self):
        xml = XML_SP.replace('<AliquotaServicos>0.05', '<AliquotaServicos>5').replace('<StatusNFe>N', '<StatusNFe>C') \
                    .replace('<ISSRetido>true', '<ISSRetido>false') \
                    .replace('<EnderecoPrestador><Cidade>3304557</Cidade></EnderecoPrestador>', '')
        n = robo.nota_de_sp(xml)
        self.assertEqual(n.aliquota, 5.0)                                  # já em %: não multiplica
        self.assertTrue(n.cancelada)
        self.assertFalse(n.iss_retido)
        self.assertEqual(n.retencoes.total, 0.0)
        self.assertEqual(n.valor_liquido, 1000.0)
        self.assertEqual(n.prestador_municipio_ibge, '3550308')            # sem endereço: prestador paulistano

    def test_sem_data_de_emissao(self):
        n = robo.nota_de_sp(XML_SP.replace('<DataEmissaoNFe>2026-09-15</DataEmissaoNFe>', ''))
        self.assertIsNone(n.emissao)
        self.assertIsNone(n.competencia)


class TestRetencoesSP(unittest.TestCase):
    def test_depois_de_14_05_2026_valor_csll_e_a_soma_e_pis_cofins_sao_debito_proprio(self):
        n = robo.nota_de_sp(XML_SP_RETENCOES)                              # emissão 15/09/2026
        r = n.retencoes
        self.assertEqual((r.iss, r.inss, r.irrf), (50.0, 110.0, 15.0))
        self.assertEqual((r.pis, r.cofins, r.csll), (0.0, 0.0, 0.0))       # 6,50 e 30,00 são débito próprio, não retenção
        self.assertEqual((r.csrf, r.csrf_quais), (46.5, 'PIS+COFINS+CSLL'))
        self.assertEqual(r.federais, 171.5)
        self.assertEqual(r.total, 221.5)
        self.assertEqual(n.valor_liquido, 778.5)
        self.assertEqual(r.quais(), ['ISS', 'INSS', 'IRRF', 'CSRF (PIS+COFINS+CSLL)'])
        self.assertIsNone(r.divergencia())                                 # SP não informa total: nada a conferir

    def test_antes_de_14_05_2026_cada_campo_e_a_propria_retencao(self):
        xml = XML_SP_RETENCOES.replace('<DataEmissaoNFe>2026-09-15', '<DataEmissaoNFe>2026-03-10')
        r = robo.nota_de_sp(xml).retencoes
        self.assertEqual((r.pis, r.cofins, r.csll), (6.5, 30.0, 46.5))
        self.assertEqual((r.csrf, r.csrf_quais), (0.0, ''))
        self.assertEqual(r.federais, 208.0)                                # 110 + 15 + 6,5 + 30 + 46,5
        self.assertEqual(r.quais(), ['ISS', 'INSS', 'IRRF', 'PIS', 'COFINS', 'CSLL'])
        # no dia da virada, já vale a regra nova
        xml = XML_SP_RETENCOES.replace('<DataEmissaoNFe>2026-09-15', '<DataEmissaoNFe>2026-05-14')
        self.assertEqual(robo.nota_de_sp(xml).retencoes.csrf, 46.5)

    def test_iss_nao_retido_nao_entra(self):
        r = robo.nota_de_sp(XML_SP_RETENCOES.replace('<ISSRetido>true', '<ISSRetido>false')).retencoes
        self.assertEqual((r.iss, r.iss_por), (0.0, ''))
        self.assertEqual(r.total, 171.5)


class TestNotaNacional(unittest.TestCase):
    def test_campos(self):
        n = robo.nota_nacional(XML_NACIONAL)
        self.assertEqual(n.fonte, 'Nacional')
        self.assertEqual(n.numero, '88')
        self.assertEqual(n.chave, CHAVE_NACIONAL)                          # pelo Id="NFS…", sem chNFSe
        self.assertEqual(n.emissao, dt.date(2026, 9, 30))                  # dhProc ganha de dhEmi
        self.assertEqual(n.competencia, robo.Competencia(2026, 9))
        self.assertEqual(n.prestador_cnpj, suporte.CNPJ_PRESTADOR)         # do emit, não do prest da DPS
        self.assertEqual(n.prestador_nome, 'Prestador Exemplo 2')
        self.assertEqual(n.prestador_municipio_ibge, '4106902')            # cMun do emit
        self.assertEqual(n.tomador_cnpj, suporte.CNPJ_A)
        self.assertEqual(n.tomador_nome, 'Empresa Exemplo A Ltda')
        self.assertEqual(n.tomador_municipio_ibge, '3509502')
        self.assertEqual(n.valor_servico, 2500.0)
        self.assertEqual(n.aliquota, 3.0)
        self.assertEqual(n.valor_iss, 75.0)
        self.assertTrue(n.iss_retido)                                      # tpRetISSQN 2
        self.assertEqual((n.retencoes.iss, n.retencoes.iss_por), (75.0, 'tomador'))
        self.assertEqual(n.retencoes.total_informado, 75.0)                # vTotalRet
        self.assertIsNone(n.retencoes.divergencia())
        self.assertEqual(n.valor_liquido, 2425.0)                          # vLiq, como veio
        self.assertFalse(n.cancelada)                                      # quem marca é chaves_canceladas
        self.assertEqual(n.papel, 'tomada')                                # sem CNPJ da empresa: o padrão

    def test_variantes(self):
        xml = XML_NACIONAL.replace('<dhProc>2026-09-30T23:59:00-03:00</dhProc>', '') \
                          .replace('<tpRetISSQN>2', '<tpRetISSQN>1') \
                          .replace('<enderNac><cMun>4106902</cMun></enderNac>', '') \
                          .replace('<pAliqAplic>3.00</pAliqAplic>', '').replace('<pAliq>3.00</pAliq>', '<pAliq>2.50</pAliq>') \
                          .replace('<nNFSe>88</nNFSe>', f'<chNFSe>{CHAVE_NACIONAL[:-1]}7</chNFSe><nNFSe>0088</nNFSe>')
        n = robo.nota_nacional(xml)
        self.assertEqual(n.emissao, dt.date(2026, 10, 1))                  # sem dhProc, vale dhEmi
        self.assertEqual(n.competencia, robo.Competencia(2026, 10))
        self.assertFalse(n.iss_retido)
        self.assertEqual(n.retencoes.total, 0.0)
        self.assertEqual(n.retencoes.divergencia(), 'vTotalRet R$ 75.00 ≠ soma das retenções R$ 0.00')   # o XML mente
        self.assertIn('conferir', n.retencoes.descricao())
        self.assertEqual(n.prestador_municipio_ibge, '3304557')            # sem cMun, vale cLocEmi
        self.assertEqual(n.aliquota, 2.5)
        self.assertEqual(n.chave, CHAVE_NACIONAL[:-1] + '7')               # chNFSe explícito tem prioridade
        self.assertEqual(n.numero, '0088')

    def test_sem_vliq_calcula_o_liquido(self):
        n = robo.nota_nacional(XML_NACIONAL.replace('<vLiq>2425.00</vLiq>', ''))
        self.assertEqual(n.valor_liquido, 2425.0)

    def test_identidade_ignora_zeros_a_esquerda_e_fonte(self):
        a = robo.nota_nacional(XML_NACIONAL.replace('<nNFSe>88', '<nNFSe>0088'))
        b = robo.nota_nacional(XML_NACIONAL)
        self.assertEqual(a.identidade, b.identidade)
        self.assertEqual(a.identidade, (suporte.CNPJ_PRESTADOR, '88', 2500.0))

    def test_papel_pelo_cnpj_da_empresa(self):
        self.assertEqual(robo.nota_nacional(XML_NACIONAL, suporte.CNPJ_A).papel, 'tomada')
        self.assertEqual(robo.nota_nacional(XML_NACIONAL, suporte.CNPJ_PRESTADOR).papel, 'prestada')
        self.assertEqual(robo.nota_nacional(XML_NACIONAL, suporte.CNPJ_B).papel, '')      # intermediária, por ex.
        self.assertEqual(robo.nota_nacional(XML_NACIONAL, '15.881.399/0001-34').papel, 'tomada')   # formatado vale
        n = robo.nota_nacional(XML_PRESTADA, suporte.CNPJ_A)
        self.assertEqual(n.papel, 'prestada')
        self.assertEqual((n.prestador_cnpj, n.tomador_cnpj), (suporte.CNPJ_A, suporte.CNPJ_B))
        self.assertEqual(n.contraparte, 'Cliente Exemplo B')
        self.assertEqual(n.tomador_municipio_ibge, '3550308')


class TestRetencoesNacional(unittest.TestCase):
    def ret(self, **kw):
        return robo.nota_nacional(xml_nacional(**kw)).retencoes

    def test_nt007_codigo_3_vretcsll_e_a_soma_das_tres(self):
        r = self.ret(trib_fed=trib_fed('110.00', '15.00', '46.50', codigo='3'), v_total_ret='246.50', v_liq='2253.50')
        self.assertEqual((r.iss, r.inss, r.irrf), (75.0, 110.0, 15.0))
        self.assertEqual((r.pis, r.cofins, r.csll), (0.0, 0.0, 0.0))
        self.assertEqual((r.csrf, r.csrf_quais), (46.5, 'PIS+COFINS+CSLL'))
        self.assertEqual(r.federais, 171.5)
        self.assertEqual(r.total, 246.5)
        self.assertIsNone(r.divergencia())                                 # bate com o vTotalRet
        self.assertEqual(r.quais(), ['ISS', 'INSS', 'IRRF', 'CSRF (PIS+COFINS+CSLL)'])
        self.assertEqual(r.descricao(), 'ISS, INSS, IRRF, CSRF (PIS+COFINS+CSLL)')

    def test_nt007_codigos_com_duas_contribuicoes(self):
        for codigo, quais in (('4', 'PIS+COFINS'), ('7', 'COFINS+CSLL'), ('9', 'PIS+CSLL')):
            with self.subTest(codigo=codigo):
                r = self.ret(trib_fed=trib_fed(v_ret_csll='30.00', codigo=codigo), v_total_ret='105.00')
                self.assertEqual((r.csrf, r.csrf_quais), (30.0, quais))
                self.assertEqual((r.pis, r.cofins, r.csll), (0.0, 0.0, 0.0))

    def test_nt007_codigo_de_um_tributo_so_vai_para_o_campo_dele(self):
        for codigo, campo in (('5', 'pis'), ('6', 'cofins'), ('8', 'csll')):
            with self.subTest(codigo=codigo):
                r = self.ret(trib_fed=trib_fed(v_ret_csll='16.25', codigo=codigo), v_total_ret='91.25')
                self.assertEqual(getattr(r, campo), 16.25)
                self.assertEqual(r.csrf, 0.0)
                self.assertEqual(r.federais, 16.25)

    def test_regra_antiga_codigo_1_pis_cofins_em_vpis_vcofins(self):
        r = self.ret(trib_fed=trib_fed(v_ret_csll='25.00', codigo='1', v_pis='16.25', v_cofins='75.00'), v_total_ret='191.25')
        self.assertEqual((r.pis, r.cofins, r.csll), (16.25, 75.0, 25.0))
        self.assertEqual(r.csrf, 0.0)
        self.assertEqual(r.quais(), ['ISS', 'PIS', 'COFINS', 'CSLL'])
        self.assertIsNone(r.divergencia())

    def test_codigo_2_ou_0_nada_de_pis_cofins(self):
        for codigo in ('0', '2'):
            with self.subTest(codigo=codigo):
                r = self.ret(trib_fed=trib_fed(codigo=codigo, v_pis='16.25', v_cofins='75.00'))
                self.assertEqual((r.pis, r.cofins, r.csll, r.csrf), (0.0, 0.0, 0.0, 0.0))   # vPis/vCofins são débito próprio
                self.assertEqual(r.total, 75.0)                            # só o ISS

    def test_sem_grupo_piscofins_vretcsll_e_so_a_csll(self):
        r = self.ret(trib_fed=trib_fed(v_ret_csll='25.00'), v_total_ret='100.00')
        self.assertEqual((r.csll, r.csrf), (25.0, 0.0))
        self.assertEqual(r.quais(), ['ISS', 'CSLL'])

    def test_sem_tribfed_so_o_iss(self):
        r = self.ret()
        self.assertEqual(r.federais, 0.0)
        self.assertEqual(r.quais(), ['ISS'])

    def test_iss_retido_pelo_intermediario(self):
        n = robo.nota_nacional(xml_nacional(tp_ret_iss='3'))
        self.assertTrue(n.iss_retido)
        self.assertEqual((n.retencoes.iss, n.retencoes.iss_por), (75.0, 'intermediário'))

    def test_total_informado_divergente_vira_aviso(self):
        r = self.ret(trib_fed=trib_fed('110.00', codigo='0'), v_total_ret='200.00')   # lido: 75 + 110 = 185
        self.assertEqual(r.total, 185.0)
        self.assertEqual(r.divergencia(), 'vTotalRet R$ 200.00 ≠ soma das retenções R$ 185.00')
        self.assertEqual(r.descricao(), 'ISS, INSS — conferir: vTotalRet R$ 200.00 ≠ soma das retenções R$ 185.00')

    def test_nota_prestada_completa(self):
        n = robo.nota_nacional(XML_PRESTADA, suporte.CNPJ_A)
        self.assertFalse(n.iss_retido)
        self.assertEqual(n.retencoes.total, 171.5)
        self.assertEqual(n.valor_liquido, 828.5)
        self.assertIsNone(n.retencoes.divergencia())


class TestNota(unittest.TestCase):
    def test_booleano_do_iss_preenche_a_retencao(self):
        n = suporte.nota('1', retido=True, valor=1000.0, aliquota=2.0)
        self.assertEqual((n.retencoes.iss, n.retencoes.iss_por), (20.0, 'tomador'))
        self.assertEqual(n.valor_liquido, 980.0)
        self.assertEqual(suporte.nota('2').retencoes.total, 0.0)

    def test_retencoes_informadas_mandam(self):
        r = robo.Retencoes(iss=20.0, iss_por='intermediário', inss=110.0)
        n = suporte.nota('1', retido=True, retencoes=r)
        self.assertEqual(n.retencoes.iss_por, 'intermediário')             # não sobrescreve
        self.assertEqual(n.valor_liquido, 870.0)

    def test_retencoes_vazia(self):
        r = robo.Retencoes()
        self.assertFalse(r.tem)
        self.assertEqual(r.quais(), [])
        self.assertEqual(r.descricao(), 'nenhuma')
        self.assertIsNone(r.divergencia())

    def test_iss_retido_e_valor_liquido_sao_derivados(self):
        """`iss_retido` e `valor_liquido` não são campos guardados: saem das retenções, e trocar as retenções
        (como faz a demonstração e o portal de escrituração) muda os dois sem precisar lembrar de recalcular."""
        n = suporte.nota('1', valor=1000.0, aliquota=2.0)
        self.assertFalse(n.iss_retido)
        self.assertEqual(n.valor_liquido, 1000.0)
        n.iss_retido = True                                                  # o jeito antigo continua valendo
        self.assertEqual((n.retencoes.iss, n.retencoes.iss_por), (20.0, 'tomador'))
        self.assertEqual(n.valor_liquido, 980.0)
        n.retencoes = robo.Retencoes(inss=110.0)                             # troca inteira: o ISS some junto
        self.assertFalse(n.iss_retido)
        self.assertEqual(n.valor_liquido, 890.0)
        n.iss_retido = False
        self.assertEqual(n.valor_liquido, 890.0)
        n.valor_liquido = 777.0                                              # vLiq lido do XML manda
        self.assertEqual(n.valor_liquido, 777.0)
        n.valor_liquido = None
        self.assertEqual(n.valor_liquido, 890.0)
        copia = dataclasses.replace(n, numero='2')                           # replace não perde nada disso
        self.assertEqual((copia.iss_retido, copia.valor_liquido, copia.retencoes.inss), (False, 890.0, 110.0))

    def test_do_tomador_exclui_o_iss_do_intermediario(self):
        self.assertEqual(robo.Retencoes(iss=20.0, iss_por='tomador', inss=11.0).do_tomador, 31.0)
        self.assertEqual(robo.Retencoes(iss=20.0, iss_por='intermediário', inss=11.0).do_tomador, 11.0)
        self.assertEqual(robo.Retencoes(iss=20.0, iss_por='intermediário').total, 20.0)
        tomada = suporte.nota('1', retencoes=robo.Retencoes(iss=20.0, iss_por='intermediário', inss=11.0))
        prestada = suporte.nota('2', papel='prestada', retencoes=robo.Retencoes(iss=20.0, iss_por='tomador', inss=11.0))
        self.assertEqual(robo.retido_pela_empresa(tomada), 11.0)
        self.assertEqual(robo.retido_pela_empresa(prestada), 31.0)
        self.assertEqual(robo.iss_retido_pela_empresa(tomada), 0.0)
        self.assertEqual(robo.iss_retido_pela_empresa(prestada), 0.0)
        self.assertEqual(robo.iss_retido_pela_empresa(suporte.nota('3', retido=True)), 20.0)


class TestChavesCanceladas(unittest.TestCase):
    def test_eventos_de_cancelamento(self):
        ch1, ch2, ch3 = CHAVE_NACIONAL[:-1] + '1', CHAVE_NACIONAL[:-1] + '2', CHAVE_NACIONAL[:-1] + '3'
        docs = [
            {'tipo': 'EVENTO', 'xml': f'<evento><infEvento><chNFSe>{ch1}</chNFSe></infEvento></evento>'},
            {'tipo': 'NFSE', 'xml': f'<NFSe><infNFSe><chNFSe>{ch2}</chNFSe></infNFSe></NFSe>'},   # nota, não evento
            {'tipo': '', 'xml': f'<pedRegEvento><infPedReg><chNFSe>{ch3}</chNFSe></infPedReg></pedRegEvento>'},
            {'tipo': 'EVENTO', 'xml': '<quebrado'},                                                  # ignorado
            {'tipo': 'EVENTO', 'xml': '<evento><infEvento/></evento>'},                              # sem chave
        ]
        self.assertEqual(robo.chaves_canceladas(docs), {ch1, ch3})
        self.assertEqual(robo.chaves_canceladas([]), set())


class TestRenumerarXml(unittest.TestCase):
    def test_troca_o_sequencial_pelo_numero_real(self):
        xml = '<CompNfse><Nfse><InfNfse><Numero>1</Numero><Outro>1</Outro></InfNfse></Nfse></CompNfse>'
        saida = robo.renumerar_xml(xml, {'1': '4521'})
        raiz = etree.fromstring(saida.encode('utf-8'))
        self.assertEqual(robo.local(raiz, 'Numero'), '4521')
        self.assertEqual(robo.local(raiz, 'Outro'), '1')                     # só os campos de número da nota
        self.assertTrue(saida.startswith("<?xml version='1.0' encoding='UTF-8'?>"))

    def test_com_namespace_e_sem_mapa(self):
        xml = '<NFSe xmlns="urn:n"><infNFSe><nNFSe> 2 </nNFSe></infNFSe></NFSe>'
        self.assertEqual(robo.local(etree.fromstring(robo.renumerar_xml(xml, {'2': '77'}).encode()), 'nNFSe'), '77')
        self.assertEqual(robo.local(etree.fromstring(robo.renumerar_xml(xml, {'9': '77'}).encode()), 'nNFSe'), '2')


class TestClientesSemRede(unittest.TestCase):
    """Só as partes que montam/desmontam mensagens — nenhuma requisição é feita."""

    def test_pedido_de_sp_tem_raiz_qualificada_e_filhos_sem_namespace(self):
        pedido = robo.ClienteSaoPaulo()._pedido(suporte.CNPJ_A, dt.date(2026, 9, 1), dt.date(2026, 9, 30), 2)
        raiz = etree.fromstring(pedido.encode('utf-8'))
        self.assertEqual(raiz.tag, '{http://www.prefeitura.sp.gov.br/nfe}PedidoConsultaNFePeriodo')
        cab = raiz.find('Cabecalho')
        self.assertIsNotNone(cab)                                          # sem namespace
        self.assertEqual(cab.get('Versao'), '1')
        self.assertEqual(cab.findtext('CPFCNPJRemetente/CNPJ'), suporte.CNPJ_A)
        self.assertEqual(cab.findtext('dtInicio'), '2026-09-01')
        self.assertEqual(cab.findtext('dtFim'), '2026-09-30')
        self.assertEqual(cab.findtext('NumeroPagina'), '2')

    def test_envelope_soap_leva_a_mensagem_como_texto(self):
        env = etree.fromstring(robo.ClienteSaoPaulo()._envelope('<a><b>1</b></a>'))
        ns = {'soap': robo.ClienteSaoPaulo.SOAP, 'nfe': robo.ClienteSaoPaulo.NS}
        msg = env.find('soap:Body/nfe:ConsultaNFeRecebidasRequest/nfe:MensagemXML', ns)
        self.assertEqual(msg.text, '<a><b>1</b></a>')                      # escapado, não como elementos
        self.assertEqual(env.findtext('soap:Body/nfe:ConsultaNFeRecebidasRequest/nfe:VersaoSchema', namespaces=ns), '1')

    def test_operacao_das_prestadas_e_a_consulta_de_emitidas(self):
        cli = robo.ClienteSaoPaulo()
        self.assertEqual(cli.OPERACOES, {'tomada': 'ConsultaNFeRecebidas', 'prestada': 'ConsultaNFeEmitidas'})
        env = etree.fromstring(cli._envelope('<a/>', 'ConsultaNFeEmitidas'))
        ns = {'soap': cli.SOAP, 'nfe': cli.NS}
        self.assertIsNotNone(env.find('soap:Body/nfe:ConsultaNFeEmitidasRequest/nfe:MensagemXML', ns))
        self.assertEqual(cli.soapaction('ConsultaNFeEmitidas'), 'http://www.prefeitura.sp.gov.br/nfe/ws/consultaNFeEmitidas')
        self.assertEqual(cli.soapaction('ConsultaNFeRecebidas'), 'http://www.prefeitura.sp.gov.br/nfe/ws/consultaNFeRecebidas')

    def test_decodifica_base64_puro_e_gzip(self):
        dec = robo.ClienteNacional._decodifica
        self.assertEqual(dec(base64.b64encode('<a>ção</a>'.encode('utf-8')).decode()), '<a>ção</a>')
        self.assertEqual(dec(base64.b64encode(gzip.compress(b'<a>gz</a>')).decode()), '<a>gz</a>')


class TestEmitenteQueNaoEOPrestador(unittest.TestCase):
    """tpEmit 2 (tomador emitiu) ou 3 (intermediário): infNFSe/emit não é o prestador — ele está em infDPS/prest."""

    def test_tp_emit_2_le_o_prestador_da_dps(self):
        xml = XML_NACIONAL.replace('<tpEmit>1</tpEmit>', '<tpEmit>2</tpEmit>') \
                          .replace(f'<emit><CNPJ>{suporte.CNPJ_PRESTADOR}</CNPJ><xNome>Prestador Exemplo 2</xNome>',
                                   f'<emit><CNPJ>{suporte.CNPJ_A}</CNPJ><xNome>Empresa Exemplo A Ltda</xNome>') \
                          .replace('<prest><CNPJ>99999999999999</CNPJ></prest>',
                                   f'<prest><CNPJ>{suporte.CNPJ_PRESTADOR}</CNPJ><xNome>Prestador Exemplo 2</xNome>'
                                   '<end><endNac><cMun>3304557</cMun></endNac></end></prest>')
        n = robo.nota_nacional(xml, suporte.CNPJ_A)
        self.assertEqual(n.prestador_cnpj, suporte.CNPJ_PRESTADOR)          # do prest, não do emit (que é o tomador)
        self.assertEqual(n.prestador_nome, 'Prestador Exemplo 2')
        self.assertEqual(n.prestador_municipio_ibge, '3304557')
        self.assertEqual(n.tomador_cnpj, suporte.CNPJ_A)
        self.assertEqual(n.papel, 'tomada')
        self.assertEqual(robo.nota_nacional(xml, suporte.CNPJ_PRESTADOR).papel, 'prestada')

    def test_tp_emit_3_sem_prest_cai_no_emit(self):
        xml = XML_NACIONAL.replace('<tpEmit>1</tpEmit>', '<tpEmit>3</tpEmit>') \
                          .replace('<prest><CNPJ>99999999999999</CNPJ></prest>', '')
        self.assertEqual(robo.nota_nacional(xml).prestador_cnpj, suporte.CNPJ_PRESTADOR)

    def test_sem_tp_emit_vale_o_emit(self):
        xml = XML_NACIONAL.replace('<tpEmit>1</tpEmit>', '')
        self.assertEqual(robo.nota_nacional(xml).prestador_cnpj, suporte.CNPJ_PRESTADOR)


if __name__ == '__main__':
    unittest.main()
