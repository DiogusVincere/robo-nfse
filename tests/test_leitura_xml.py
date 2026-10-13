# -*- coding: utf-8 -*-
"""Seções 5 (partes puras dos clientes), 6 (XML → Nota) e 11 (renumeração) com XMLs sintéticos mínimos."""
import base64
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
</NFe>'''

CHAVE_NACIONAL = 'NFS' + '35503082' + '0' * 41 + '1'                # NFS + 50 dígitos

XML_NACIONAL = f'''<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.00">
  <infNFSe Id="{CHAVE_NACIONAL}">
    <cLocEmi>3304557</cLocEmi>
    <nNFSe>88</nNFSe>
    <dhProc>2026-09-30T23:59:00-03:00</dhProc>
    <emit><CNPJ>{suporte.CNPJ_PRESTADOR}</CNPJ><xNome>Prestador Exemplo 2</xNome>
      <enderNac><cMun>4106902</cMun></enderNac></emit>
    <valores><vServ>2500.00</vServ><vISSQN>75.00</vISSQN></valores>
    <DPS><infDPS Id="DPS000">
      <dhEmi>2026-10-01T08:00:00-03:00</dhEmi>
      <prest><CNPJ>99999999999999</CNPJ></prest>
      <toma><CNPJ>{suporte.CNPJ_A}</CNPJ><xNome>Empresa Exemplo A Ltda</xNome></toma>
      <valores><vServPrest><vServ>2500.00</vServ></vServPrest>
        <trib><tribMun><tribISSQN>1</tribISSQN><tpRetISSQN>2</tpRetISSQN><pAliqAplic>3.00</pAliqAplic></tribMun></trib>
      </valores>
    </infDPS></DPS>
  </infNFSe>
</NFSe>'''


class TestNotaDeSP(unittest.TestCase):
    def test_campos(self):
        n = robo.nota_de_sp(XML_SP)
        self.assertEqual(n.fonte, 'SP')
        self.assertEqual(n.numero, '4521')
        self.assertEqual(n.chave, 'SP-4521-ABCD1234')
        self.assertEqual(n.emissao, dt.date(2026, 9, 15))
        self.assertEqual(n.competencia, robo.Competencia(2026, 9))
        self.assertEqual(n.prestador_cnpj, suporte.CNPJ_PRESTADOR)
        self.assertEqual(n.prestador_nome, 'Prestador Exemplo 1')
        self.assertEqual(n.prestador_municipio_ibge, '3304557')
        self.assertEqual(n.tomador_cnpj, suporte.CNPJ_A)
        self.assertEqual(n.valor_servico, 1000.0)
        self.assertEqual(n.aliquota, 5.0)                                  # 0.05 → 5%
        self.assertEqual(n.valor_iss, 50.0)
        self.assertTrue(n.iss_retido)
        self.assertFalse(n.cancelada)
        self.assertEqual(n.xml, XML_SP)                                    # o XML original fica na nota

    def test_variantes(self):
        xml = XML_SP.replace('<AliquotaServicos>0.05', '<AliquotaServicos>5').replace('<StatusNFe>N', '<StatusNFe>C') \
                    .replace('<ISSRetido>true', '<ISSRetido>false') \
                    .replace('<EnderecoPrestador><Cidade>3304557</Cidade></EnderecoPrestador>', '')
        n = robo.nota_de_sp(xml)
        self.assertEqual(n.aliquota, 5.0)                                  # já em %: não multiplica
        self.assertTrue(n.cancelada)
        self.assertFalse(n.iss_retido)
        self.assertEqual(n.prestador_municipio_ibge, '3550308')            # sem endereço: prestador paulistano

    def test_sem_data_de_emissao(self):
        n = robo.nota_de_sp(XML_SP.replace('<DataEmissaoNFe>2026-09-15</DataEmissaoNFe>', ''))
        self.assertIsNone(n.emissao)
        self.assertIsNone(n.competencia)


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
        self.assertEqual(n.valor_servico, 2500.0)
        self.assertEqual(n.aliquota, 3.0)
        self.assertEqual(n.valor_iss, 75.0)
        self.assertTrue(n.iss_retido)                                      # tpRetISSQN 2
        self.assertFalse(n.cancelada)                                      # quem marca é chaves_canceladas

    def test_variantes(self):
        xml = XML_NACIONAL.replace('<dhProc>2026-09-30T23:59:00-03:00</dhProc>', '') \
                          .replace('<tpRetISSQN>2', '<tpRetISSQN>1') \
                          .replace('<enderNac><cMun>4106902</cMun></enderNac>', '') \
                          .replace('<pAliqAplic>3.00</pAliqAplic>', '<pAliq>2.50</pAliq>') \
                          .replace('<nNFSe>88</nNFSe>', f'<chNFSe>{CHAVE_NACIONAL[:-1]}7</chNFSe><nNFSe>0088</nNFSe>')
        n = robo.nota_nacional(xml)
        self.assertEqual(n.emissao, dt.date(2026, 10, 1))                  # sem dhProc, vale dhEmi
        self.assertEqual(n.competencia, robo.Competencia(2026, 10))
        self.assertFalse(n.iss_retido)
        self.assertEqual(n.prestador_municipio_ibge, '3304557')            # sem cMun, vale cLocEmi
        self.assertEqual(n.aliquota, 2.5)
        self.assertEqual(n.chave, CHAVE_NACIONAL[:-1] + '7')               # chNFSe explícito tem prioridade
        self.assertEqual(n.numero, '0088')

    def test_identidade_ignora_zeros_a_esquerda_e_fonte(self):
        a = robo.nota_nacional(XML_NACIONAL.replace('<nNFSe>88', '<nNFSe>0088'))
        b = robo.nota_nacional(XML_NACIONAL)
        self.assertEqual(a.identidade, b.identidade)
        self.assertEqual(a.identidade, (suporte.CNPJ_PRESTADOR, '88', 2500.0))


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

    def test_decodifica_base64_puro_e_gzip(self):
        dec = robo.ClienteNacional._decodifica
        self.assertEqual(dec(base64.b64encode('<a>ção</a>'.encode('utf-8')).decode()), '<a>ção</a>')
        self.assertEqual(dec(base64.b64encode(gzip.compress(b'<a>gz</a>')).decode()), '<a>gz</a>')


if __name__ == '__main__':
    unittest.main()
