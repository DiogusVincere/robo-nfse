# Robô NFS-e Tomados

[![testes](https://github.com/DiogusVincere/robo-nfse-tomados/actions/workflows/testes.yml/badge.svg)](https://github.com/DiogusVincere/robo-nfse-tomados/actions/workflows/testes.yml)

Extrai, organiza, classifica e escritura as notas fiscais de serviço (NFS-e) que uma empresa **tomou** no mês,
sem navegador e sem repetir nada do que já foi feito.

Versão de portfólio em arquivo único (`robo_nfse_tomados.py`): mostra a estrutura e a lógica do robô usado em
produção num escritório contábil, sem credenciais, chaves, nomes de clientes nem endereços de sistemas privados.
Roda de ponta a ponta no modo `--demo`, com dados fictícios e um portal simulado.

## O problema

Toda empresa que contrata um serviço (o **tomador**) precisa conhecer as NFS-e emitidas contra ela. Quando o
prestador é de **outro município**, a prefeitura do tomador não enxerga essa nota, e o tomador é obrigado a
declará-la ("escriturar") no portal da própria prefeitura, recolhendo o ISS quando ele é retido.

Feito à mão, isso significa abrir portal por portal, empresa por empresa, todo mês: baixar o que existe em duas
fontes diferentes, descobrir o que é de fora, digitar nota a nota num formulário e guardar os comprovantes. É
repetitivo, e um erro de digitação (número da nota, alíquota) só aparece quando a fiscalização bate.

## O que o robô faz

Uma execução, ponta a ponta, para uma lista de empresas e uma competência:

| Etapa | O que acontece | Como |
|---|---|---|
| **1. Extração** | Busca as NFS-e tomadas por cada empresa, 100% em segundo plano, com o certificado A1 dela | Nota Paulistana (SOAP assinado com XMLDSig + mTLS) e Sistema Nacional NFS-e (API REST por NSU, mTLS, incremental, com pausa, backoff e `Retry-After`) |
| **2. Organização** | Cada XML vai para a pasta do cliente na competência certa (competência = mês da **emissão**), com espelho em PDF | Reaproveita a pasta do mês que a equipe já tenha criado à mão (`09-2026`, `09.2026`, `092026`); documentos de outras competências são arquivados, não perdidos |
| **3. Classificação** | Separa "do município" (não se declara), "fora do município" (precisa ser escriturada) e canceladas | Pelo código IBGE do município do **prestador**; deduplica a mesma nota vinda pelas duas fontes |
| **4. Escrituração** | Declara no portal municipal as notas de fora | Consulta anti-duplicidade antes; travas antes de gravar (número do documento e ISS recalculado); salva o comprovante; confirma de novo no portal; renova a sessão se o portal derrubar |
| **5. Pós-escrituração** | Guia de ISS retido, exportação dos XML para o sistema contábil e relatório por responsável | Renumera os XML exportados (o portal troca o número da nota por um sequencial interno); Excel com duas abas; e-mail opcional |

## Decisões de projeto

- **Idempotência.** Toda etapa pode ser repetida sem duplicar nada: o último NSU por CNPJ fica guardado; antes de
  emitir, o robô consulta o que o portal já lista e o seu próprio *ledger* de chaves escrituradas. Rodar duas vezes
  só gera "já escriturada".
- **Falha isolada.** Erro numa empresa vira linha de pendência no relatório e o robô segue para a próxima. Nada
  interrompe o lote.
- **Segurança do A1.** O CNPJ é lido **de dentro** do certificado (CN ou `otherName` ICP-Brasil), não do nome do
  arquivo. A chave privada só existe em PEM temporário durante a sessão mTLS e é apagada ao sair do contexto. Senhas
  vêm de um provedor configurável (variável de ambiente, cofre), nunca do código.
- **Gentileza com os serviços públicos.** Pausa entre chamadas e entre empresas, backoff em 429/5xx, respeito ao
  `Retry-After`, paginação até acabar.
- **Travas antes de gravar.** O formulário é preenchido e **lido de volta** antes de confirmar: o número do documento
  tem de ser o da nota e o ISS que o portal calculou tem de bater com valor × alíquota (tolerância de R$ 0,01). Isso
  pega, por exemplo, a alíquota padrão do portal que não foi trocada pela da nota. O que não passa é descartado e
  vira pendência, nunca gravado errado.

## Demonstração offline

```
pip install -r requirements.txt
python robo_nfse_tomados.py --demo --saida ./demo
```

Seis empresas fictícias, notas geradas com semente fixa (as mesmas a cada execução) e um portal simulado em memória
que, de propósito, tem um "defeito": aplica alíquota padrão de 5% em 1 de cada 7 notas, e às vezes derruba a sessão.
Primeira execução:

```
14:19:35    sessão caiu (tentativa 1) — renovando e refazendo a nota 20747
14:19:36 [1/6] 100 Empresa Exemplo A Ltda: 10 nota(s), 6 escriturada(s), 1 pendência(s)  (faltam ~1s)
14:19:36 [2/6] 101 Empresa Exemplo B Ltda: 9 nota(s), 5 escriturada(s), 1 pendência(s)  (faltam ~0s)
14:19:36 [3/6] 102 Empresa Exemplo C Ltda: 4 nota(s), 3 escriturada(s)  (faltam ~0s)
14:19:36 [4/6] 103 Empresa Exemplo D Ltda: 4 nota(s), 3 escriturada(s)  (faltam ~0s)
14:19:36 [5/6] 104 Empresa Exemplo E Ltda: 9 nota(s), 0 escriturada(s)  (faltam ~0s)
14:19:36 [6/6] 105 Empresa Exemplo F Ltda: 7 nota(s), 0 escriturada(s)  (faltam ~0s)
14:19:37 relatório: demo\_relatorios\Analista 1 09-2026.xlsx
14:19:37 relatório: demo\_relatorios\Analista 2 09-2026.xlsx
```

As duas pendências são a trava do ISS barrando o "defeito" do portal (`ISS do portal R$ 50.00 ≠ valor × alíquota
R$ 20.00`); a sessão derrubada foi renovada e a nota refeita. As empresas 104 e 105 são de outros municípios: suas
notas de fora aparecem no relatório como "escriturar no portal do tomador", não neste portal.

Segunda execução, na mesma pasta:

```
14:19:37 [1/6] 100 Empresa Exemplo A Ltda: 10 nota(s), 1 escriturada(s), 6 já escriturada(s)  (faltam ~0s)
14:19:38 [2/6] 101 Empresa Exemplo B Ltda: 9 nota(s), 1 escriturada(s), 5 já escriturada(s)  (faltam ~0s)
14:19:38 [3/6] 102 Empresa Exemplo C Ltda: 4 nota(s), 0 escriturada(s), 3 já escriturada(s)  (faltam ~0s)
14:19:38 [4/6] 103 Empresa Exemplo D Ltda: 4 nota(s), 0 escriturada(s), 3 já escriturada(s)  (faltam ~0s)
14:19:38 [5/6] 104 Empresa Exemplo E Ltda: 9 nota(s), 0 escriturada(s)  (faltam ~0s)
14:19:38 [6/6] 105 Empresa Exemplo F Ltda: 7 nota(s), 0 escriturada(s)  (faltam ~0s)
```

Nada do que foi gravado é gravado de novo. A única nota escriturada agora em cada uma das duas primeiras empresas
é a que a trava barrou na primeira execução; ela ganha nova chance, e desta vez o portal calculou o ISS certo. Na
terceira execução tudo vem como "já escriturada" e zero gravações.

O que a demonstração deixa em `./demo`:

```
demo/
├── 100 - Empresa Exemplo A Ltda/NFE/2026/09-2026/Tomados/
│   ├── Tomados SP/Autorizadas/            XML (e PDF, com reportlab) de cada nota da fonte SP
│   ├── Tomados Portal Nacional/Autorizadas/  idem, fonte Nacional (há também Canceladas/)
│   ├── Notas Escrituradas/                comprovante PDF de cada nota declarada
│   ├── Importação XML Tomados/            XML exportados e renumerados para o sistema contábil
│   └── Guia ISS retido 09-2026.pdf
├── ... (uma pasta por empresa)
├── _estado/estado.json                    último NSU por CNPJ + ledger do que já foi escriturado
└── _relatorios/Analista 1 09-2026.xlsx    um Excel por responsável: abas Empresas (resumo) e Notas (detalhe)
```

## Uso real

```
python robo_nfse_tomados.py --competencia 09/2026 --empresas empresas.json --certificados ./certificados --saida ./saida
```

Opções: `--competencia MM/AAAA` (padrão: o mês anterior), `--responsavel "Nome"` (só as empresas daquela pessoa).

**Variáveis de ambiente** (nenhum segredo fica em arquivo):

| Variável | Para quê |
|---|---|
| `NFSE_PFX_SENHA_<CNPJ>` | Senha do `.pfx` de cada empresa; `<CNPJ>` com 14 dígitos (ex.: `NFSE_PFX_SENHA_15881399000134`) |
| `NFSE_SMTP_HOST`, `NFSE_SMTP_PORTA` (padrão 587), `NFSE_SMTP_USUARIO`, `NFSE_SMTP_SENHA` | Envio do relatório por e-mail (STARTTLS). Sem elas, o relatório só é salvo |
| `NFSE_EMAIL_PARA` | Destinatário do relatório |

**`empresas.json`** (ver [`exemplos/empresas.exemplo.json`](exemplos/empresas.exemplo.json)): uma lista de objetos
com `codigo`, `razao`, `cnpj` (só dígitos), `municipio_ibge` (7 dígitos) e `responsavel`. Campos extras são
ignorados.

```json
[
  {"codigo": "100", "razao": "Empresa Exemplo A Ltda", "cnpj": "15881399000134",
   "municipio_ibge": "3509502", "responsavel": "Analista 1"}
]
```

**Pasta de certificados:** qualquer árvore de subpastas com arquivos `.pfx`. O robô abre cada um com a senha do
ambiente, lê o CNPJ de dentro do certificado e usa, para cada empresa, o **mais recente ainda válido**. O nome do
arquivo ou da pasta não é levado em conta.

**Município do portal:** `Config.municipio_escrituracao_ibge` (padrão `3509502` no código) é o município do portal
de escrituração. Só empresas desse município têm as notas de fora escrituradas; as outras recebem no relatório a
lista do que escriturar.

**Sem um `PortalMunicipal` implementado** (a situação desta versão: `main()` passa `portal=None`), o robô faz as
etapas 1 a 3 e o relatório: extrai das duas fontes, organiza as pastas, classifica, e lista nota a nota o que
precisa ser escriturado. A escrituração (etapa 4) e a exportação (etapa 5) exigem uma implementação da interface
descrita abaixo, que no robô de produção conversa com o portal JSF de uma prefeitura e depende da autenticação de
cada escritório.

## Arquitetura

O arquivo tem 14 seções, em ordem de dependência. No robô de produção cada uma é um módulo:

| Seção | Conteúdo | Principais nomes |
|---|---|---|
| 1 | Configuração e utilitários | `Config`, `Competencia`, `para_float`, `nome_seguro`, `local`, `grupo` |
| 2 | Modelos | `Empresa`, `Nota` (o mesmo formato para as duas fontes; `identidade` para deduplicar), `ResultadoEmpresa` |
| 3 | Certificado A1 e mTLS | `SenhaProvider`/`SenhaDoAmbiente`, `ler_certificado`, `certificados_por_cnpj`, `sessao_mtls` |
| 4 | Assinatura XML (XMLDSig enveloped, RSA-SHA1) | `assinar_enveloped` |
| 5 | Clientes dos web services | `ClienteSaoPaulo` (SOAP, paginado), `ClienteNacional` (REST por NSU, backoff) |
| 6 | Leitura dos XML → `Nota` | `nota_de_sp`, `nota_nacional`, `chaves_canceladas` |
| 7 | Pastas e estado | `pasta_da_competencia`, `EstadoRobo` (NSU, ledger, arquivo; gravação atômica) |
| 8 | Espelho em PDF (opcional) | `gerar_espelho_pdf` (só com `reportlab`) |
| 9 | Classificação | `classificar` |
| 10 | Escrituração: interface + travas | `PortalMunicipal`, `Previa`, `SessaoPerdida`, `conferir_antes_de_gravar`, `escriturar_empresa` |
| 11 | Exportação para o sistema contábil | `renumerar_xml`, `exportar_para_sistema_contabil` |
| 12 | Relatório e e-mail | `gerar_relatorio` (openpyxl), `enviar_por_email` |
| 13 | Orquestrador | `extrair_empresa`, `salvar_xmls`, `executar`, `Progresso` |
| 14 | Demonstração e linha de comando | `PortalSimulado`, `demonstracao`, `cnpj_ficticio`, `carregar_empresas`, `main` |

**A interface `PortalMunicipal`** é o que o robô precisa de qualquer portal de escrituração; as travas e a lógica de
sessão (`escriturar_empresa`) valem para qualquer implementação:

| Método | Papel |
|---|---|
| `abrir_sessao(empresa)` | Autentica (ou renova a sessão, depois de um `SessaoPerdida`) |
| `escrituradas(empresa, competencia) -> set` | Identidades (CNPJ do prestador, nº, valor) já declaradas no mês: a consulta anti-duplicidade e a confirmação final |
| `preencher(empresa, nota) -> Previa` | Preenche o formulário e devolve o que o portal mostra (nº do documento, ISS calculado), **sem gravar** |
| `gravar() -> bytes` | Confirma o formulário preenchido e devolve o comprovante em PDF |
| `descartar()` | Abandona o formulário (a trava não deixou gravar) |
| `emitir_guia_iss_retido(empresa, competencia) -> bytes | None` | Guia do ISS retido do mês |
| `exportar_xml_tomados(empresa, competencia) -> (xmls, mapa)` | XML exportados pelo portal e o mapa {sequencial do portal: nº real do documento} |

`PortalSimulado` (seção 14) é uma implementação completa em memória, usada na demonstração e nos testes.

## Fontes públicas

Os dois web services que o código consulta são públicos e documentados pelos próprios órgãos. Ambos exigem o
certificado A1 do tomador (mTLS).

- **Nota Paulistana (Prefeitura de São Paulo)**: SOAP 1.1 em `https://nfe.prefeitura.sp.gov.br/ws/lotenfe.asmx`,
  operação `ConsultaNFeRecebidas` (`SOAPAction` `http://www.prefeitura.sp.gov.br/nfe/ws/consultaNFeRecebidas`), com
  a mensagem `PedidoConsultaNFePeriodo` assinada (XMLDSig enveloped, RSA-SHA1) e enviada como texto dentro de
  `MensagemXML`. Até 50 notas por página; o cliente segue até uma página vir com menos de 50.
- **Sistema Nacional NFS-e (Ambiente de Dados Nacional)**: REST em
  `https://adn.nfse.gov.br/contribuintes/DFe/{NSU}?lote=true&cnpjConsulta={CNPJ}`, que devolve até 50 documentos
  a partir do NSU pedido (XML em base64, às vezes gzip). Os eventos de cancelamento chegam pela mesma distribuição.
  O cliente guarda o último NSU por CNPJ e trata 404 como "nada novo", 429/5xx com backoff e `Retry-After`.

## Testes

```
python -m unittest discover -s tests -v
```

77 testes, nenhum acesso à rede, tudo em pastas temporárias (passam no Windows e no Linux). O que cobrem:

| Arquivo | Cobre |
|---|---|
| `test_utilitarios.py` | `Competencia` (os três formatos de texto, mês anterior, fim de fevereiro, pasta), `para_float` (pt-BR e en), `nome_seguro`, `digitos`, `local`/`grupo`, `cnpj_ficticio` (dígitos verificadores) |
| `test_leitura_xml.py` | `nota_de_sp` e `nota_nacional` com XMLs sintéticos (alíquota 0.05 → 5%, `tpRetISSQN` 2 = retido, `dhProc` antes de `dhEmi`, chave pelo `Id` NFS…), `chaves_canceladas`, `renumerar_xml`, montagem do pedido SOAP e do envelope, decodificação base64/gzip |
| `test_classificacao.py` | `classificar` (do município × fora × canceladas; dedup entre fontes com preferência pela Nacional) e `conferir_antes_de_gravar` (número diferente, ISS fora da tolerância, ok) |
| `test_estado.py` | `EstadoRobo` (NSU monotônico, ledger, arquivar/arquivadas, gravação atômica), `pasta_da_competencia` reaproveitando `09.2026`/`092026`/`09 2026`, `salvar_xmls` |
| `test_relatorio.py` | `gerar_relatorio` (abre com openpyxl, confere cabeçalhos e linhas), espelho em PDF com e sem reportlab, e-mail sem configuração não envia, `Progresso` |
| `test_escrituracao.py` | `PortalSimulado` + `escriturar_empresa`: a trava barra o "defeito" 1 em 7, sessão perdida é renovada (e vira pendência quando nunca volta), ledger e consulta ao portal impedem duplicar, guia só com ISS retido, gravação não confirmada vira aviso; exportação renumerada; `executar` sem portal, com falha isolada e com empresa de outro município |
| `test_demonstracao.py` | `demonstracao()` três vezes na mesma pasta com portal de semente fixa (2ª: só as barradas são gravadas, o resto "já escriturada"; 3ª: zero gravações), a demonstração como ela é, `main --demo`, `carregar_empresas` com o arquivo de exemplo |
| `test_certificado.py` | Certificados autoassinados gerados no teste pela `cryptography` (RSA 2048, PFX em memória): `assinar_enveloped` (estrutura `Signature/SignedInfo/Reference URI=""`, `DigestValue` = SHA-1 do C14N do documento sem a assinatura, assinatura verificada com a chave pública, adulteração detectada), `ler_certificado` pelo CN e pelo `otherName` ICP-Brasil, `certificados_por_cnpj` pulando o vencido, `sessao_mtls` criando e apagando os PEM |

O workflow [`testes.yml`](.github/workflows/testes.yml) roda a suíte em Python 3.12 e 3.13 (Ubuntu), depois a
demonstração duas vezes e confere os dois relatórios.

## Limitações

- **O portal municipal real não está incluído.** `PortalMunicipal` é só a interface; a implementação de produção
  depende da autenticação e do portal de cada prefeitura. Sem ela, o robô extrai, organiza, classifica e relata.
- **RSA-SHA1** na assinatura XML é exigência do web service da Prefeitura de São Paulo, não uma escolha.
- **Sem *retries* no SOAP**: o cliente de SP levanta o erro na primeira falha HTTP (o cliente Nacional tem backoff).
  No orquestrador, a falha fica isolada na empresa.
- O espelho em PDF depende do `reportlab` (opcional); sem ele, só o XML é salvo.
- O CNPJ em `empresas.json` precisa vir só com dígitos: é comparado como texto com o CNPJ lido dos XML.

## Licença

[MIT](LICENSE).
