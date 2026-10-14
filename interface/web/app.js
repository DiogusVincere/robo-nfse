/* Interface local do Robô NFS-e Tomados. Vanilla JS, sem build. Fala só com o processo local (127.0.0.1). */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const TOKEN = window.TOKEN;
  const moedaBR = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

  // ---- utilidades ---------------------------------------------------------------------------------------
  function toast(texto, tipo) {
    const el = $('toast');
    el.textContent = texto;
    el.className = 'toast' + (tipo ? ' toast--' + tipo : '');
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, 5000);
  }

  async function api(caminho, opcoes) {
    const o = Object.assign({ method: 'GET' }, opcoes || {});
    o.headers = Object.assign({ 'X-Token': TOKEN }, o.headers || {});
    if (o.json !== undefined) {
      o.body = JSON.stringify(o.json);
      o.headers['Content-Type'] = 'application/json';
      delete o.json;
    }
    const r = await fetch(caminho, o);
    if (o.bruto) return r;
    let dados = null;
    try { dados = await r.json(); } catch (e) { dados = null; }
    if (!r.ok) {
      const erro = new Error((dados && dados.erro) || ('erro ' + r.status));
      erro.status = r.status;
      throw erro;
    }
    return dados;
  }

  const cnpjFmt = (d) => (d && d.length === 14) ? d.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, '$1.$2.$3/$4-$5') : (d || '');
  const dataBR = (iso) => iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—';
  const normalizar = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const escapar = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function lerBase64(arquivo) {
    return new Promise((resolve, reject) => {
      const leitor = new FileReader();
      leitor.onload = () => resolve(String(leitor.result).split(',')[1] || '');
      leitor.onerror = () => reject(new Error('não consegui ler o arquivo'));
      leitor.readAsDataURL(arquivo);
    });
  }

  // ---- certificado ---------------------------------------------------------------------------------------
  let arquivoPfx = null;
  let certificado = null;

  function definirArquivo(arquivo) {
    if (!arquivo) return;
    if (!/\.(pfx|p12)$/i.test(arquivo.name)) {
      toast('Escolha um arquivo .pfx ou .p12 (certificado A1).', 'erro');
      return;
    }
    arquivoPfx = arquivo;
    certificado = null;
    $('pfx-nome').textContent = arquivo.name + ' · ' + Math.max(1, Math.round(arquivo.size / 1024)) + ' KB';
    $('cert-info').hidden = true;
    $('cert-status').textContent = '';
    $('solta').classList.add('solta--ok');
  }

  $('btn-escolher').addEventListener('click', () => $('pfx').click());
  $('pfx').addEventListener('change', (e) => definirArquivo(e.target.files[0]));
  const solta = $('solta');
  solta.addEventListener('dragover', (e) => { e.preventDefault(); solta.classList.add('solta--arrastando'); });
  solta.addEventListener('dragleave', () => solta.classList.remove('solta--arrastando'));
  solta.addEventListener('drop', (e) => {
    e.preventDefault();
    solta.classList.remove('solta--arrastando');
    definirArquivo(e.dataTransfer.files[0]);
  });
  $('btn-olho').addEventListener('click', () => {
    const s = $('senha');
    s.type = s.type === 'password' ? 'text' : 'password';
    $('btn-olho').textContent = s.type === 'password' ? 'mostrar' : 'ocultar';
  });

  async function conferirCertificado() {
    if (!arquivoPfx) { toast('Escolha o arquivo .pfx primeiro.', 'erro'); return null; }
    $('cert-status').textContent = 'Conferindo…';
    $('btn-conferir').disabled = true;
    try {
      const info = await api('/api/certificado', { method: 'POST', json: { pfx_b64: await lerBase64(arquivoPfx), senha: $('senha').value } });
      certificado = info;
      const el = $('cert-info');
      el.className = 'cert-info' + (info.vencido ? ' cert-info--vencido' : '');
      el.innerHTML = '<strong>' + escapar(info.titular) + '</strong>' +
        '<span>CNPJ ' + escapar(info.cnpj_formatado) + '</span>' +
        '<span>' + (info.vencido ? 'Vencido em ' : 'Válido até ') + escapar(dataBR(info.validade)) + '</span>';
      el.hidden = false;
      $('cert-status').textContent = info.vencido ? 'certificado vencido' : 'certificado ok';
      return info;
    } catch (e) {
      certificado = null;
      $('cert-info').hidden = true;
      $('cert-status').textContent = '';
      toast(e.message, 'erro');
      return null;
    } finally {
      $('btn-conferir').disabled = false;
    }
  }
  $('btn-conferir').addEventListener('click', conferirCertificado);

  // ---- municípios (lista do IBGE embutida) ------------------------------------------------------------
  let municipios = null;          // [[id, nome, uf], ...]
  let indicePorId = null;
  async function carregarMunicipios() {
    if (municipios) return municipios;
    const r = await fetch('/municipios.json');
    municipios = await r.json();
    indicePorId = new Map(municipios.map((m) => [m[0], m[1] + ' (' + m[2] + ')']));
    return municipios;
  }
  const nomeMunicipio = (id) => (indicePorId && indicePorId.get(String(id))) || String(id || '—');

  const campoMun = $('municipio');
  const listaMun = $('municipio-lista');
  let sugestoes = [];
  let ativo = -1;

  function fecharLista() { listaMun.hidden = true; ativo = -1; }
  function escolherMunicipio(m) {
    campoMun.value = m[1] + ' (' + m[2] + ')';
    $('municipio-ibge').value = m[0];
    campoMun.classList.add('entrada--ok');
    fecharLista();
  }
  function renderSugestoes() {
    if (!sugestoes.length) { fecharLista(); return; }
    listaMun.innerHTML = sugestoes.map((m, i) =>
      '<li class="' + (i === ativo ? 'ativo' : '') + '" data-i="' + i + '"><span>' + escapar(m[1]) + '</span><small>' + escapar(m[2]) + ' · ' + escapar(m[0]) + '</small></li>').join('');
    listaMun.hidden = false;
  }
  campoMun.addEventListener('focus', () => { carregarMunicipios(); });
  campoMun.addEventListener('input', async () => {
    $('municipio-ibge').value = '';
    campoMun.classList.remove('entrada--ok');
    const q = normalizar(campoMun.value.trim());
    if (!q) { fecharLista(); return; }
    await carregarMunicipios();
    if (/^\d{7}$/.test(q)) {
      const m = municipios.find((x) => x[0] === q);
      if (m) { escolherMunicipio(m); return; }
    }
    const comeca = [], contem = [];
    for (const m of municipios) {
      const n = normalizar(m[1]);
      if (n.startsWith(q)) comeca.push(m);
      else if (n.includes(q)) contem.push(m);
      if (comeca.length >= 8) break;
    }
    sugestoes = comeca.concat(contem).slice(0, 8);
    ativo = sugestoes.length ? 0 : -1;
    renderSugestoes();
  });
  campoMun.addEventListener('keydown', (e) => {
    if (listaMun.hidden) return;
    if (e.key === 'ArrowDown') { ativo = Math.min(ativo + 1, sugestoes.length - 1); renderSugestoes(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { ativo = Math.max(ativo - 1, 0); renderSugestoes(); e.preventDefault(); }
    else if (e.key === 'Enter') { if (ativo >= 0) escolherMunicipio(sugestoes[ativo]); e.preventDefault(); }
    else if (e.key === 'Escape') fecharLista();
  });
  listaMun.addEventListener('mousedown', (e) => {
    const li = e.target.closest('li');
    if (li) { escolherMunicipio(sugestoes[Number(li.dataset.i)]); e.preventDefault(); }
  });
  document.addEventListener('click', (e) => { if (!e.target.closest('.campo--busca')) fecharLista(); });

  // ---- competência padrão: mês anterior ---------------------------------------------------------------
  (function () {
    const d = new Date();
    d.setDate(1);
    d.setMonth(d.getMonth() - 1);
    $('competencia').value = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
    $('competencia').max = new Date().toISOString().slice(0, 7);
  })();

  // ---- busca e andamento -----------------------------------------------------------------------------
  let ocupado = false;
  let totalMensagens = 0;
  let temporizador = null;

  function mostrarAndamento() {
    $('vazio').hidden = true;
    $('resultado').hidden = true;
    $('andamento').hidden = false;
    $('log').textContent = '';
    $('erro').hidden = true;
    $('barra-envolve').classList.add('barra--ativa');
    totalMensagens = 0;
    ocupado = true;
    $('btn-buscar').disabled = true;
    $('btn-simular').disabled = true;
  }

  function anexarMensagens(mensagens) {
    if (!mensagens.length) return;
    const log = $('log');
    for (const m of mensagens) {
      const linha = document.createElement('div');
      linha.className = 'log__linha log__linha--' + m.nivel;
      linha.textContent = m.hora + '  ' + m.texto;
      log.appendChild(linha);
    }
    log.scrollTop = log.scrollHeight;
  }

  const FASES = { preparando: 'preparando', certificado: 'lendo o certificado', buscando: 'buscando nas fontes', empacotando: 'montando o zip', concluido: 'concluído', erro: 'falhou' };

  async function consultar() {
    try {
      const est = await api('/api/estado?desde=' + totalMensagens);
      const t = est.trabalho;
      if (!t) return;
      anexarMensagens(t.mensagens);
      totalMensagens = t.total_mensagens;
      $('fase').textContent = FASES[t.fase] || t.fase;
      $('fase').className = 'selo ' + (t.fase === 'erro' ? 'selo--vermelho' : t.fase === 'concluido' ? 'selo--verde' : 'selo--azul');
      $('cronometro').textContent = t.segundos + ' s';
      if (t.concluido) {
        clearInterval(temporizador);
        temporizador = null;
        ocupado = false;
        $('btn-buscar').disabled = false;
        $('btn-simular').disabled = false;
        $('barra-envolve').classList.remove('barra--ativa');
        if (t.erro) {
          $('erro').textContent = 'A busca não terminou: ' + t.erro;
          $('erro').hidden = false;
          $('barra').style.width = '100%';
        } else {
          $('barra').style.width = '100%';
          await mostrarResultado(t.resultado, t.zip);
        }
      }
    } catch (e) {
      anexarMensagens([{ hora: new Date().toLocaleTimeString('pt-BR'), texto: 'sem resposta do processo local: ' + e.message, nivel: 'erro' }]);
    }
  }

  function acompanhar() {
    mostrarAndamento();
    consultar();
    temporizador = setInterval(consultar, 1000);
  }

  $('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (ocupado) return;
    if (!arquivoPfx) { toast('Escolha o arquivo .pfx do certificado.', 'erro'); return; }
    if (!$('senha').value) { toast('Digite a senha do certificado.', 'erro'); $('senha').focus(); return; }
    if (!$('municipio-ibge').value) { toast('Escolha o município da empresa na lista.', 'erro'); campoMun.focus(); return; }
    if (!$('competencia').value) { toast('Informe a competência.', 'erro'); return; }
    if (!certificado) {
      const info = await conferirCertificado();
      if (!info) return;
    }
    if (certificado.vencido && !confirm('Este certificado está vencido e os web services vão recusá-lo. Tentar mesmo assim?')) return;
    const [ano, mes] = $('competencia').value.split('-');
    try {
      await api('/api/buscar', {
        method: 'POST',
        json: {
          pfx_b64: await lerBase64(arquivoPfx),
          senha: $('senha').value,
          competencia: mes + '/' + ano,
          municipio_ibge: $('municipio-ibge').value,
          razao: certificado.titular,
          desde_o_inicio: $('desde-inicio').checked,
        },
      });
      acompanhar();
    } catch (err) {
      toast(err.message, 'erro');
    }
  });

  $('btn-simular').addEventListener('click', async () => {
    if (ocupado) return;
    try {
      await api('/api/simular', { method: 'POST', json: {} });
      acompanhar();
    } catch (err) {
      toast(err.message, 'erro');
    }
  });

  // ---- resultado ---------------------------------------------------------------------------------------
  let notas = [];
  let filtroAtual = 'todas';
  let zipNome = '';

  const CHIPS = [
    ['todas', 'Todas', () => true],
    ['fora', 'De fora do município', (n) => !n.cancelada && !n.situacao.startsWith('do município')],
    ['municipio', 'Do município', (n) => n.situacao.startsWith('do município')],
    ['canceladas', 'Canceladas', (n) => n.cancelada],
    ['retido', 'ISS retido', (n) => n.iss_retido && !n.cancelada],
  ];

  function classeSituacao(n) {
    if (n.cancelada) return 'selo--cinza';
    if (n.situacao.startsWith('do município')) return 'selo--verde';
    if (n.situacao.startsWith('NÃO')) return 'selo--vermelho';
    if (n.situacao.startsWith('escriturada') || n.situacao.startsWith('já')) return 'selo--azul';
    return 'selo--ambar';
  }

  function renderTabela() {
    const q = normalizar($('filtro').value.trim());
    const regra = CHIPS.find((c) => c[0] === filtroAtual)[2];
    const visiveis = notas.filter((n) => regra(n) && (!q || normalizar(n.prestador_nome + ' ' + n.numero + ' ' + n.prestador_cnpj + ' ' + n.empresa).includes(q)));
    const corpo = $('tabela').querySelector('tbody');
    if (!visiveis.length) {
      corpo.innerHTML = '<tr><td colspan="8" class="texto-centro texto-suave">Nenhuma nota com esse filtro.</td></tr>';
    } else {
      corpo.innerHTML = visiveis.map((n) =>
        '<tr' + (n.cancelada ? ' class="cancelada"' : '') + '>' +
        '<td><span class="fonte fonte--' + (n.fonte === 'SP' ? 'sp' : 'nac') + '">' + escapar(n.fonte) + '</span></td>' +
        '<td class="mono">' + escapar(n.numero) + '</td>' +
        '<td>' + escapar(dataBR(n.emissao)) + '</td>' +
        '<td><div class="prest"><strong>' + escapar(n.prestador_nome || '—') + '</strong><small>' + escapar(cnpjFmt(n.prestador_cnpj)) + (n.empresa ? ' · tomador: ' + escapar(n.empresa) : '') + '</small></div></td>' +
        '<td>' + escapar(nomeMunicipio(n.prestador_municipio_ibge)) + '</td>' +
        '<td class="num">' + moedaBR.format(n.valor) + '</td>' +
        '<td class="num">' + moedaBR.format(n.iss) + (n.iss_retido ? ' <span class="retido" title="ISS retido pelo tomador">retido</span>' : '') + '</td>' +
        '<td><span class="selo ' + classeSituacao(n) + '">' + escapar(n.situacao) + '</span></td>' +
        '</tr>').join('');
    }
    $('res-rodape').textContent = visiveis.length + ' de ' + notas.length + ' nota(s) na tela.';
  }

  function renderChips() {
    $('chips').innerHTML = CHIPS.map((c) => {
      const qtd = notas.filter(c[2]).length;
      return '<button type="button" class="chip' + (filtroAtual === c[0] ? ' chip--ativo' : '') + '" data-f="' + c[0] + '">' + c[1] + ' <small>' + qtd + '</small></button>';
    }).join('');
  }
  $('chips').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    filtroAtual = b.dataset.f;
    renderChips();
    renderTabela();
  });
  $('filtro').addEventListener('input', renderTabela);

  async function mostrarResultado(res, zip) {
    await carregarMunicipios();
    const varias = res.empresas.length > 1;
    // com várias empresas (modo simulado), a linha mostra também quem é o tomador
    notas = res.notas.map((n) => Object.assign({}, n, { empresa: varias ? (n.empresa_razao || '') : '' }));
    zipNome = zip || '';
    const t = res.totais;
    $('res-titulo').textContent = 'competência ' + res.competencia;
    $('res-modo').textContent = res.modo === 'simulado' ? 'dados simulados' : 'dados reais';
    $('res-modo').className = 'selo ' + (res.modo === 'simulado' ? 'selo--ambar' : 'selo--verde');
    const cartoes = [
      ['Notas distintas', t.notas, t.documentos_lidos + ' documento(s) lido(s)'],
      ['De fora do município', t.fora, 'precisam ser escrituradas'],
      ['Do município', t.do_municipio, 'não se declaram'],
      ['Canceladas', t.canceladas, ''],
      ['Valor dos serviços', moedaBR.format(t.valor), 'notas ativas'],
      ['ISS retido', moedaBR.format(t.iss_retido), 'de ' + moedaBR.format(t.iss) + ' de ISS'],
    ];
    $('totais').innerHTML = cartoes.map((c) => '<div class="total"><small>' + escapar(c[0]) + '</small><strong>' + escapar(c[1]) + '</strong><span>' + escapar(c[2]) + '</span></div>').join('');
    $('zip-nome').textContent = zipNome;
    $('pasta-local').textContent = res.pasta_local ? 'Os arquivos também ficam em ' + res.pasta_local : '';
    const pend = res.empresas.flatMap((e) => e.pendencias.map((p) => (varias ? e.razao + ': ' : '') + p));
    if (pend.length) {
      $('pendencias').innerHTML = '<strong>' + pend.length + ' pendência(s)</strong><ul>' + pend.map((p) => '<li>' + escapar(p) + '</li>').join('') + '</ul>';
      $('pendencias').hidden = false;
    } else {
      $('pendencias').hidden = true;
    }
    filtroAtual = 'todas';
    $('filtro').value = '';
    renderChips();
    renderTabela();
    $('resultado').hidden = false;
    $('resultado').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  $('btn-baixar').addEventListener('click', async () => {
    const b = $('btn-baixar');
    b.disabled = true;
    try {
      const r = await api('/api/baixar', { bruto: true });
      if (!r.ok) throw new Error('o zip não está mais disponível');
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = zipNome || 'nfse-tomadas.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      toast('Download iniciado.');
    } catch (e) {
      toast(e.message, 'erro');
    } finally {
      b.disabled = false;
    }
  });

  $('btn-nova').addEventListener('click', async () => {
    try { await api('/api/limpar', { method: 'POST', json: {} }); } catch (e) { /* segue */ }
    $('resultado').hidden = true;
    $('andamento').hidden = true;
    $('vazio').hidden = false;
    $('senha').value = '';
    certificado = null;
    $('cert-info').hidden = true;
    $('cert-status').textContent = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  $('btn-encerrar').addEventListener('click', async () => {
    if (ocupado && !confirm('Há uma busca em andamento. Encerrar mesmo assim?')) return;
    if (!ocupado && !confirm('Encerrar o processo local? Esta página deixa de funcionar.')) return;
    try { await api('/api/encerrar', { method: 'POST', json: {} }); } catch (e) { /* já caiu */ }
    document.body.innerHTML = '<div class="encerrado"><h1>Interface encerrada</h1><p>O processo local foi finalizado. Pode fechar esta aba.</p></div>';
  });

  window.addEventListener('beforeunload', (e) => {
    if (ocupado) { e.preventDefault(); e.returnValue = ''; }
  });

  // Se o processo já tinha um trabalho (página recarregada no meio), retoma o acompanhamento.
  api('/api/estado').then((est) => {
    if (est.trabalho) {
      if (est.trabalho.concluido && !est.trabalho.erro) {
        $('vazio').hidden = true;
        mostrarResultado(est.trabalho.resultado, est.trabalho.zip);
      } else {
        acompanhar();
      }
    }
  }).catch(() => toast('Não consegui falar com o processo local. Ele ainda está rodando?', 'erro'));
})();
