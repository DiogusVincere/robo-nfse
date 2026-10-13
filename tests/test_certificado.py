# -*- coding: utf-8 -*-
"""Seções 3 e 4: certificado A1, sessão mTLS (sem requisição) e assinatura XMLDSig.

Os certificados são autoassinados, gerados aqui mesmo pela `cryptography`, para empresas que não existem."""
import base64
import datetime as dt
import hashlib
import os
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import suporte
except ImportError:
    import suporte

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

robo = suporte.robo

SENHA = 'senha-de-teste'
CNPJ_CN = '12345678000195'
CNPJ_SAN = suporte.CNPJ_B
XML_PEDIDO = ('<nfe:PedidoConsultaNFePeriodo xmlns:nfe="http://www.prefeitura.sp.gov.br/nfe">'
              '<Cabecalho Versao="1"><CPFCNPJRemetente><CNPJ>12345678000195</CNPJ></CPFCNPJRemetente>'
              '<dtInicio>2026-09-01</dtInicio><dtFim>2026-09-30</dtFim><NumeroPagina>1</NumeroPagina>'
              '</Cabecalho></nfe:PedidoConsultaNFePeriodo>')


def _certificado(cn: str, san=None, dias_validade: int = 365, inicio_ha_dias: int = 1):
    """Par chave + certificado autoassinado. `san` = lista de GeneralName (ex.: OtherName do e-CNPJ)."""
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(x509.NameOID.COUNTRY_NAME, 'BR'),
                      x509.NameAttribute(x509.NameOID.COMMON_NAME, cn)])
    agora = dt.datetime.now(dt.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(agora - dt.timedelta(days=inicio_ha_dias))
               .not_valid_after(agora - dt.timedelta(days=inicio_ha_dias) + dt.timedelta(days=dias_validade)))
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName(san), critical=False)
    return chave, builder.sign(chave, hashes.SHA256())


def _pfx(caminho: Path, chave, cert, senha: str = SENHA):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(pkcs12.serialize_key_and_certificates(
        b'exemplo', chave, cert, None, serialization.BestAvailableEncryption(senha.encode())))
    return caminho


def _other_name_cnpj(cnpj: str) -> x509.OtherName:
    """otherName 2.16.76.1.3.3 com o CNPJ, codificado em DER como PrintableString."""
    valor = cnpj.encode()
    return x509.OtherName(x509.ObjectIdentifier(robo.OID_CNPJ_ICP_BRASIL), b'\x13' + bytes([len(valor)]) + valor)


class TestCertificado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.pasta = Path(cls._tmp.name)
        cls.chave_a, cls.cert_a = _certificado(f'EMPRESA EXEMPLO:{CNPJ_CN}')
        cls.pfx_a = _pfx(cls.pasta / 'cliente-a' / 'a.pfx', cls.chave_a, cls.cert_a)
        cls.chave_b, cls.cert_b = _certificado('EMPRESA EXEMPLO DOIS LTDA', san=[_other_name_cnpj(CNPJ_SAN)])
        cls.pfx_b = _pfx(cls.pasta / 'cliente-b' / 'b.pfx', cls.chave_b, cls.cert_b)
        chave_v, cert_v = _certificado(f'EMPRESA EXEMPLO:{CNPJ_CN}', dias_validade=300, inicio_ha_dias=400)
        cls.pfx_vencido = _pfx(cls.pasta / 'cliente-a' / 'vencido.pfx', chave_v, cert_v)   # mesmo CNPJ, vencido
        chave_s, cert_s = _certificado('SEM CNPJ NENHUM')
        cls.pfx_sem_cnpj = _pfx(cls.pasta / 'outros' / 'sem.pfx', chave_s, cert_s)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_ler_certificado_pelo_cn(self):
        c = robo.ler_certificado(self.pfx_a, SENHA)
        self.assertEqual(c.cnpj, CNPJ_CN)
        self.assertEqual(c.titular, 'EMPRESA EXEMPLO')
        self.assertEqual(c.caminho, self.pfx_a)
        self.assertIsNotNone(c.validade.tzinfo)
        self.assertGreater(c.validade, dt.datetime.now(dt.timezone.utc))

    def test_ler_certificado_pelo_othername_icp_brasil(self):
        c = robo.ler_certificado(self.pfx_b, SENHA)
        self.assertEqual(c.cnpj, CNPJ_SAN)
        self.assertEqual(c.titular, 'EMPRESA EXEMPLO DOIS LTDA')

    def test_sem_cnpj_e_senha_errada(self):
        with self.assertRaises(ValueError) as cm:
            robo.ler_certificado(self.pfx_sem_cnpj, SENHA)
        self.assertIn('não achei o CNPJ', str(cm.exception))
        with self.assertRaises(Exception):
            robo.ler_certificado(self.pfx_a, 'senha errada')

    def test_certificados_por_cnpj_escolhe_o_valido_de_cada_um(self):
        os.utime(self.pfx_vencido, (time.time() + 60, time.time() + 60))     # o vencido é o mais recente da pasta
        ambiente = {f'NFSE_PFX_SENHA_{CNPJ_CN}': SENHA, f'NFSE_PFX_SENHA_{CNPJ_SAN}': SENHA}
        with mock.patch.dict(os.environ, ambiente):
            achados = robo.certificados_por_cnpj(self.pasta, robo.SenhaDoAmbiente(), [CNPJ_CN, CNPJ_SAN, suporte.CNPJ_A])
        self.assertEqual(set(achados), {CNPJ_CN, CNPJ_SAN})                    # CNPJ_A não tem certificado
        self.assertEqual(achados[CNPJ_CN].caminho, self.pfx_a)                  # o vencido foi pulado
        self.assertEqual(achados[CNPJ_SAN].caminho, self.pfx_b)

    def test_senha_do_ambiente(self):
        with mock.patch.dict(os.environ, {f'NFSE_PFX_SENHA_{CNPJ_CN}': 'abc'}):
            self.assertEqual(robo.SenhaDoAmbiente().senha('12.345.678/0001-95'), 'abc')   # formatado também vale
            with self.assertRaises(LookupError):
                robo.SenhaDoAmbiente().senha(CNPJ_SAN)

    def test_sessao_mtls_cria_e_apaga_os_pem(self):
        cert = robo.ler_certificado(self.pfx_a, SENHA)
        with robo.sessao_mtls(cert, SENHA) as sess:
            cert_pem, key_pem = sess.cert
            self.assertTrue(Path(cert_pem).exists() and Path(key_pem).exists())
            self.assertTrue(Path(cert_pem).parent.name.startswith('mtls_'))
            self.assertIn(b'BEGIN CERTIFICATE', Path(cert_pem).read_bytes())
            self.assertIn(b'PRIVATE KEY', Path(key_pem).read_bytes())
            pasta = Path(cert_pem).parent
        self.assertFalse(pasta.exists())                                        # a chave privada não fica no disco


class TestAssinatura(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.chave, cls.cert = _certificado(f'EMPRESA EXEMPLO:{CNPJ_CN}')
        cls.pfx = _pfx(Path(cls._tmp.name) / 'a.pfx', cls.chave, cls.cert)
        cls.certificado = robo.ler_certificado(cls.pfx, SENHA)
        cls.assinado = robo.assinar_enveloped(XML_PEDIDO, cls.certificado, SENHA)
        cls.raiz = etree.fromstring(cls.assinado.encode('utf-8'))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _ds(self, el, caminho):
        return el.find(caminho, {'ds': robo.DS})

    def test_estrutura_da_assinatura(self):
        self.assertTrue(self.assinado.startswith("<?xml version='1.0' encoding='UTF-8'?>"))
        sig = self._ds(self.raiz, 'ds:Signature')
        self.assertIsNotNone(sig)
        self.assertIs(sig, self.raiz[-1])                                       # enveloped: último filho da raiz
        info = self._ds(sig, 'ds:SignedInfo')
        self.assertEqual(self._ds(info, 'ds:CanonicalizationMethod').get('Algorithm'),
                         'http://www.w3.org/TR/2001/REC-xml-c14n-20010315')
        self.assertEqual(self._ds(info, 'ds:SignatureMethod').get('Algorithm'), robo.DS + 'rsa-sha1')
        ref = self._ds(info, 'ds:Reference')
        self.assertEqual(ref.get('URI'), '')
        transforms = [t.get('Algorithm') for t in ref.findall('ds:Transforms/ds:Transform', {'ds': robo.DS})]
        self.assertEqual(transforms, [robo.DS + 'enveloped-signature', 'http://www.w3.org/TR/2001/REC-xml-c14n-20010315'])
        self.assertEqual(self._ds(ref, 'ds:DigestMethod').get('Algorithm'), robo.DS + 'sha1')
        x509cert = self._ds(sig, 'ds:KeyInfo/ds:X509Data/ds:X509Certificate').text
        self.assertEqual(base64.b64decode(x509cert), self.cert.public_bytes(serialization.Encoding.DER))

    def test_digest_e_o_sha1_do_c14n_sem_a_assinatura(self):
        digest = self._ds(self.raiz, 'ds:Signature/ds:SignedInfo/ds:Reference/ds:DigestValue').text
        original = etree.tostring(etree.fromstring(XML_PEDIDO.encode()), method='c14n', exclusive=False,
                                  with_comments=False)
        self.assertEqual(base64.b64decode(digest), hashlib.sha1(original).digest())
        # o mesmo resultado tirando a Signature do documento assinado (é o que o verificador faz)
        copia = etree.fromstring(self.assinado.encode('utf-8'))
        copia.remove(self._ds(copia, 'ds:Signature'))
        sem_assinatura = etree.tostring(copia, method='c14n', exclusive=False, with_comments=False)
        self.assertEqual(hashlib.sha1(sem_assinatura).digest(), base64.b64decode(digest))

    def test_assinatura_verifica_com_a_chave_publica(self):
        info = self._ds(self.raiz, 'ds:Signature/ds:SignedInfo')
        valor = base64.b64decode(self._ds(self.raiz, 'ds:Signature/ds:SignatureValue').text)
        c14n_info = etree.tostring(info, method='c14n', exclusive=False, with_comments=False)
        self.cert.public_key().verify(valor, c14n_info, padding.PKCS1v15(), hashes.SHA1())   # não levanta
        self.assertEqual(len(valor), 256)                                       # RSA 2048
        with self.assertRaises(InvalidSignature):                               # outra chave não verifica
            rsa.generate_private_key(65537, 2048).public_key().verify(valor, c14n_info, padding.PKCS1v15(),
                                                                       hashes.SHA1())
        with self.assertRaises(InvalidSignature):                               # SignedInfo adulterado não verifica
            self.cert.public_key().verify(valor, c14n_info.replace(b'sha1', b'sha2'), padding.PKCS1v15(), hashes.SHA1())

    def test_assinatura_deterministica_e_digest_que_muda_com_o_conteudo(self):
        """RSA PKCS#1 v1.5 é determinística para a mesma chave e os mesmos bytes; outro conteúdo, outro digest."""
        outra = robo.assinar_enveloped(XML_PEDIDO, self.certificado, SENHA)
        self.assertEqual(outra, self.assinado)
        texto = robo.assinar_enveloped(XML_PEDIDO.replace('2026-09-30', '2026-09-29'), self.certificado, SENHA)
        self.assertNotEqual(etree.fromstring(texto.encode()).find('.//ds:DigestValue', {'ds': robo.DS}).text,
                            self._ds(self.raiz, 'ds:Signature/ds:SignedInfo/ds:Reference/ds:DigestValue').text)

    def test_conteudo_original_preservado(self):
        self.assertEqual(robo.local(self.raiz, 'CNPJ'), CNPJ_CN)
        self.assertEqual(robo.local(self.raiz, 'dtFim'), '2026-09-30')
        self.assertEqual(self.raiz.tag, '{http://www.prefeitura.sp.gov.br/nfe}PedidoConsultaNFePeriodo')


if __name__ == '__main__':
    unittest.main()
