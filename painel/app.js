'use strict';
// Painel do Claude: a conversa da sessão do tmux, com envio de prompt, anexo e teclas.
// O servidor (bin/painel-servidor.py) segura cada /api/eventos até ter novidade,
// então a página fica sempre em dia sem ficar perguntando a cada segundo.

const $ = (s) => document.querySelector(s);
const el = {
  app: $('#app'), titulo: $('#titulo'), ponto: $('#ponto'),
  rolagem: $('#rolagem'), conversa: $('#conversa'), vazio: $('#vazio'), anteriores: $('#bt-anteriores'),
  fim: $('#bt-fim'), rede: $('#aviso-rede'), texto: $('#texto'), enviar: $('#bt-enviar'),
  anexar: $('#bt-anexar'), arquivo: $('#arquivo'), anexos: $('#anexos'), compositor: $('#compositor'),
  pergunta: $('#pergunta'), pergTexto: $('#perg-texto'), pergOpcoes: $('#perg-opcoes'),
  pergForm: $('#perg-form'), pergCampo: $('#perg-campo'), btTela: $('#bt-tela'), pergVerTela: $('#perg-tela'),
  folha: $('#folha'), tela: $('#tela'), aviso: $('#aviso'),
  fechado: $('#fechado'), sugestoes: $('#sugestoes'), busca: $('#busca'), gaveta: $('#gaveta'),
  listaSessoes: $('#lista-sessoes'), btConversas: $('#bt-conversas'), btFecharClaude: $('#bt-fechar-claude'),
  favicon: $('#favicon'), pergFechar: $('#perg-fechar'),
  listaEntregas: $('#lista-entregas'), visor: $('#visor'), visorCorpo: $('#visor-corpo'),
  visorNome: $('#visor-nome'), visorAcoes: $('#visor-acoes'),
};

const S = {
  sessao: null, total: 0, inicio: 0, marca: '', marcaTela: '', estado: null,
  telaAberta: false, falhas: 0, ctrl: null, grupo: null, carregado: false,
  ferramentas: new Map(), resultados: new Map(), anexos: [], pendentes: [],
  pergAssinatura: '', ultimoDia: '', comandos: [], sessoes: [], fecharConfirma: null,
};
const TOQUE = matchMedia('(pointer: coarse)').matches;

// Ícones do sprite do index.html. A faísca (marca do Claude) também vem de lá; o favicon copia o desenho dela.
const ic = (nome, classe = '') => `<svg class="ic${classe ? ' ' + classe : ''}" aria-hidden="true"><use href="#i-${nome}"/></svg>`;
// Faísca viva: a marca do Claude cortada nos 12 raios dela. Cada raio fica deitado no eixo x dentro
// de um <g> girado até o ângulo da ponta, então o scaleX do CSS estica e encolhe só o comprimento.
// Os pares e os ímpares se alternam (como o ✳/✻ do spinner do CLI), cada um com um atraso próprio.
const RAIOS = [
  [13.7, 'M15.92 11.87L15.98 11.92L17.52 11.69L18.17 11.57L19.74 11.18L22.73 10.68L23.62 11.00L24.23 11.51L24.27 12.00L23.24 12.89L21.55 12.90L17.62 12.93L16.27 12.92L16.09 12.96L12.00 12.00Z'],
  [42.1, 'M16.06 10.91L16.13 10.99L17.66 11.05L20.36 11.05L23.78 11.10L24.27 11.45L24.33 12.00L24.05 12.19L21.30 12.44L20.17 12.45L17.65 12.54L17.56 12.63L12.00 12.00Z'],
  [57.1, 'M17.53 11.16L17.67 11.26L18.46 11.24L22.69 11.18L23.66 11.67L23.86 12.00L23.71 12.63L23.25 13.12L20.88 13.23L18.30 13.24L16.04 13.14L12.00 12.00Z'],
  [93.0, 'M15.95 10.56L16.03 10.69L23.31 10.99L23.70 11.29L24.02 12.00L23.59 12.63L22.86 12.99L21.37 12.74L19.43 12.46L17.88 12.22L15.97 12.03L15.33 11.90L15.29 11.91L12.00 12.00Z'],
  [124.2, 'M14.76 10.22L14.86 10.32L17.29 10.41L20.95 10.56L23.45 10.95L23.82 11.20L23.91 12.00L23.33 12.32L22.61 12.32L18.76 12.04L16.40 11.91L14.98 11.75L14.85 11.84L12.00 12.00Z'],
  [146.6, 'M14.57 10.77L14.62 10.80L22.18 10.85L23.20 11.35L23.36 12.00L22.90 12.59L22.57 12.67L20.26 12.71L20.26 12.71L20.26 12.71L14.87 12.32L14.67 12.47L12.00 12.00Z'],
  [181.0, 'M14.47 10.88L14.55 11.00L14.78 11.00L15.57 11.03L18.27 11.06L20.61 11.11L22.88 11.19L23.45 11.30L24.00 12.00L23.95 12.35L23.48 12.68L22.79 12.63L21.27 12.56L18.99 12.44L17.34 12.38L14.88 12.16L14.49 12.17L14.44 12.33L12.00 12.00Z'],
  [213.7, 'M14.23 10.96L14.40 10.96L14.54 10.99L17.39 11.01L20.45 10.99L22.10 11.06L22.97 11.07L23.53 11.25L24.22 12.00L24.08 12.96L23.31 13.40L23.09 13.48L21.97 13.40L19.56 13.23L16.47 13.09L16.00 13.04L15.93 13.21L12.00 12.00Z'],
  [244.3, 'M16.00 11.04L16.06 11.09L16.38 11.06L19.17 10.90L22.04 10.68L23.25 10.55L23.88 10.66L24.58 10.89L25.17 12.00L25.11 12.43L24.56 13.27L24.05 13.49L22.51 13.43L20.06 13.37L16.66 13.46L15.65 13.48L14.80 13.33L14.53 13.31L12.00 12.00Z'],
  [279.9, 'M14.82 11.59L14.84 11.74L14.99 11.72L16.69 11.55L18.79 11.42L21.49 11.19L22.25 11.14L23.21 11.35L23.82 12.00L23.65 12.62L23.06 13.21L22.61 13.22L20.74 13.26L17.78 13.21L15.80 13.19L12.00 12.00Z'],
  [310.9, 'M15.87 11.06L16.01 11.22L16.35 11.24L17.98 11.13L20.63 11.02L21.72 11.04L22.96 11.09L23.65 11.22L24.32 12.00L23.97 13.31L22.87 13.82L21.15 13.90L19.71 13.98L17.60 14.14L16.05 14.44L12.00 12.00Z'],
  [351.4, 'M16.66 11.22L16.72 11.34L16.91 11.35L19.82 11.17L21.39 11.13L23.26 11.09L24.02 11.60L24.06 12.00L23.61 12.75L21.59 12.94L19.24 13.05L15.72 13.34L15.67 13.37L12.00 12.00Z'],
];
const MIOLO = 'M15.83 12.80L15.74 13.91L15.71 16.19L13.24 16.02L11.92 15.29L10.53 14.44L9.51 13.08L9.56 11.63L9.40 8.81L12.08 9.16L13.82 8.46L16.50 10.53Z';
const DESVIO = [0, .1, -.08, .06, -.12, .04, .09, -.05, .11, -.1, .03, -.07];
const faisca = (classe = 'viva') => `<svg class="faisca ${classe}" viewBox="0 0 24 24" aria-hidden="true"><path d="${MIOLO}"/>` +
  RAIOS.map(([ang, d], k) => `<g transform="rotate(${ang} 12 12)"><path class="raio${k % 2 ? ' impar' : ''}" ` +
    `style="animation-delay:${((k % 2 ? -0.8 : 0) + DESVIO[k]).toFixed(2)}s" d="${d}"/></g>`).join('') + '</svg>';
const FAISCA_D = $('#i-faisca path').getAttribute('d');
const CARREGANDO = `<div class="carregando">${faisca()}Carregando</div>`;
el.ponto.innerHTML = faisca('');
const ROTULO_TECLA = {
  Up: ic('cima'), Down: ic('baixo'), Left: ic('esquerda'), Right: ic('direita'),
  Escape: 'esc', BTab: ic('shift') + 'Tab', Enter: ic('enviar') + 'Enter',
};

// ------------------------------------------------------------------ util

const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const normal = (s) => String(s || '').replace(/\s+/g, ' ').trim();

async function api(caminho, { metodo = 'GET', corpo = null, sinal = null } = {}) {
  const op = { method: metodo, headers: {}, signal: sinal, cache: 'no-store' };
  if (metodo !== 'GET') {
    op.headers['X-Painel'] = '1';
    op.headers['Content-Type'] = 'application/json';
    op.body = JSON.stringify(corpo || {});
  }
  const r = await fetch(caminho, op);
  let dados = null;
  try { dados = await r.json(); } catch { /* resposta sem json */ }
  if (!r.ok) {
    const erro = new Error((dados && dados.erro) || `O PC respondeu com erro ${r.status}.`);
    erro.status = r.status;
    throw erro;
  }
  return dados;
}

let avisoTimer = null;
function avisar(msg, erro = false, ms = 0) {
  el.aviso.textContent = msg;
  el.aviso.className = 'visivel' + (erro ? ' erro' : '');
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => { el.aviso.className = erro ? 'erro' : ''; }, ms || (erro ? 4200 : 2200));
}

async function copiar(texto, botao) {
  try {
    await navigator.clipboard.writeText(texto);
  } catch {
    const t = document.createElement('textarea');
    t.value = texto; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove();
  }
  if (!botao) return avisar('Copiado');
  const uso = botao.querySelector('use'), rot = botao.querySelector('.rot');
  botao.classList.add('copiado');
  if (uso) uso.setAttribute('href', '#i-ok');
  if (rot) rot.textContent = 'copiado';
  clearTimeout(botao.timer);
  botao.timer = setTimeout(() => {
    botao.classList.remove('copiado');
    if (uso) uso.setAttribute('href', '#i-copiar');
    if (rot) rot.textContent = 'copiar';
  }, 1300);
}

function hora(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function dia(ts) {
  if (!ts) return '';
  const d = new Date(ts), hoje = new Date(), ontem = new Date(Date.now() - 864e5);
  if (d.toDateString() === hoje.toDateString()) return 'Hoje';
  if (d.toDateString() === ontem.toDateString()) return 'Ontem';
  return d.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit' });
}

function duracaoCli(ms) {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function duracao(ms) {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60), r = s % 60;
  if (m < 60) return r ? `${m} min ${r} s` : `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

function linkar(textoEscapado) {
  return textoEscapado.replace(/(^|[\s(])(https?:\/\/[^\s<]+[^\s<.,;:!?)'"])/g,
    (m, antes, url) => `${antes}<a href="${url}" target="_blank" rel="noopener">${url}</a>`);
}

// ------------------------------------------------------------------ markdown

function enfase(s) {
  return s
    .replace(/\*\*(?=\S)([^*\n]+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(?=\S)([^_\n]+?)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\w)/g, '$1<em>$2</em>')
    .replace(/(^|[^\w])_(?=\S)([^_\n]+?)(?<=\S)_(?!\w)/g, '$1<em>$2</em>')
    .replace(/~~(?=\S)([^~\n]+?)~~/g, '<del>$1</del>');
}

// Código e links viram marcadores antes da ênfase, pra um "_" de URL não virar itálico.
function inline(src) {
  const guardados = [];
  const guardar = (html) => { guardados.push(html); return `\u0000${guardados.length - 1}\u0000`; };
  let s = String(src).replace(/`([^`\n]+)`/g, (m, c) => guardar(`<code>${esc(c)}</code>`));
  s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (m, t, u) => guardar(`<a href="${esc(u)}" target="_blank" rel="noopener">${enfase(esc(t))}</a>`));
  s = s.replace(/(^|[\s(])(https?:\/\/[^\s<]+[^\s<.,;:!?)'"])/g,
    (m, antes, u) => antes + guardar(`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>`));
  s = enfase(esc(s));
  for (let n = 0; n < 3 && s.includes('\u0000'); n++) s = s.replace(/\u0000(\d+)\u0000/g, (m, i) => guardados[+i]);
  return s;
}

const RE_LISTA = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const RE_CERCA = /^\s*(```+|~~~+)\s*([\w+#.-]*)\s*$/;
const indentacao = (l) => l.match(/^\s*/)[0].replace(/\t/g, '    ').length;

function celulas(l) {
  let s = l.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));
}

function blocoCodigo(codigo, ling) {
  return `<div class="codigo"><div class="codigo-topo"><span>${esc(ling || 'texto')}</span>` +
    `<button class="copiar" data-copiar="pre">${ic('copiar')}<span class="rot">copiar</span></button></div><pre><code>${esc(codigo)}</code></pre></div>`;
}

function comecaBloco(l, prox) {
  return RE_CERCA.test(l) || /^#{1,6}\s/.test(l) || /^\s*>/.test(l) || RE_LISTA.test(l) ||
    /^\s*([-*_])(\s*\1){2,}\s*$/.test(l) ||
    (l.includes('|') && prox !== undefined && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(prox));
}

function lista(L, i) {
  const base = indentacao(L[i]);
  const ordenada = /^\s*\d+[.)]/.test(L[i]);
  const inicio = ordenada ? parseInt(L[i].trim(), 10) : 1;
  const itens = [];
  while (i < L.length) {
    const l = L[i];
    if (!l.trim()) {
      const prox = L[i + 1];
      if (prox !== undefined && prox.trim() && (indentacao(prox) > base || (indentacao(prox) === base && RE_LISTA.test(prox)))) { i++; continue; }
      break;
    }
    const ind = indentacao(l);
    const m = l.match(RE_LISTA);
    if (m && ind === base) { itens.push({ linhas: [m[3]], sub: [] }); i++; continue; }
    if (ind > base && itens.length) {
      const buf = [];
      while (i < L.length && (L[i].trim() ? indentacao(L[i]) > base : (L[i + 1] !== undefined && L[i + 1].trim() && indentacao(L[i + 1]) > base))) {
        buf.push(L[i]); i++;
      }
      const menor = Math.min(...buf.filter((x) => x.trim()).map(indentacao));
      const atual = itens[itens.length - 1];
      const corpo = buf.map((x) => x.replace(/\t/g, '    ').slice(Math.min(menor, indentacao(x)))).join('\n');
      if (!atual.sub.length && !RE_LISTA.test(buf[0]) && !RE_CERCA.test(buf[0]) && !buf[0].trim().startsWith('|')) {
        atual.linhas.push(...corpo.split('\n'));
      } else atual.sub.push(corpo);
      continue;
    }
    if (ind === base && !m && itens.length) { itens[itens.length - 1].linhas.push(l.trim()); i++; continue; }
    break;
  }
  const tag = ordenada ? 'ol' : 'ul';
  const html = itens.map((it) => {
    let texto = it.linhas.join('\n');
    let classe = '', caixa = '';
    const t = texto.match(/^\[([ xX])\]\s+/);
    if (t) {
      const feita = t[1] !== ' ';
      caixa = ic(feita ? 'caixa-ok' : 'caixa');
      texto = texto.slice(t[0].length);
      classe = ` class="tarefa${feita ? ' feita' : ''}"`;
    }
    return `<li${classe}>${caixa}${texto.split('\n').map(inline).join('<br>')}${it.sub.map(md).join('')}</li>`;
  }).join('');
  return { html: `<${tag}${ordenada && inicio !== 1 ? ` start="${inicio}"` : ''}>${html}</${tag}>`, i };
}

function md(src) {
  const L = String(src).replace(/\r/g, '').split('\n');
  const out = [];
  let i = 0;
  while (i < L.length) {
    const l = L[i];
    let m;
    if ((m = l.match(RE_CERCA))) {
      const cerca = m[1], buf = [];
      i++;
      while (i < L.length && !L[i].trim().startsWith(cerca)) buf.push(L[i++]);
      i++;
      out.push(blocoCodigo(buf.join('\n'), m[2]));
      continue;
    }
    if (!l.trim()) { i++; continue; }
    if ((m = l.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/))) {
      const n = m[1].length;
      out.push(`<h${n}>${inline(m[2])}</h${n}>`); i++; continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) { out.push('<hr>'); i++; continue; }
    if (l.includes('|') && L[i + 1] !== undefined && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(L[i + 1])) {
      const cab = celulas(l);
      const alin = celulas(L[i + 1]).map((c) => (c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : ''));
      i += 2;
      const linhas = [];
      while (i < L.length && L[i].trim() && L[i].includes('|')) linhas.push(celulas(L[i++]));
      const st = (k) => (alin[k] ? ` style="text-align:${alin[k]}"` : '');
      out.push(`<div class="tabela"><table><thead><tr>${cab.map((c, k) => `<th${st(k)}>${inline(c)}</th>`).join('')}</tr></thead><tbody>` +
        linhas.map((r) => `<tr>${cab.map((_, k) => `<td${st(k)}>${inline(r[k] || '')}</td>`).join('')}</tr>`).join('') +
        '</tbody></table></div>');
      continue;
    }
    if (/^\s*>/.test(l)) {
      const buf = [];
      while (i < L.length && /^\s*>/.test(L[i])) buf.push(L[i++].replace(/^\s*> ?/, ''));
      out.push(`<blockquote>${md(buf.join('\n'))}</blockquote>`);
      continue;
    }
    if (RE_LISTA.test(l)) { const r = lista(L, i); out.push(r.html); i = r.i; continue; }
    const buf = [l];
    i++;
    while (i < L.length && L[i].trim() && !comecaBloco(L[i], L[i + 1])) buf.push(L[i++]);
    out.push(`<p>${buf.map((x) => inline(x.trim())).join('<br>')}</p>`);
  }
  return out.join('');
}

// ------------------------------------------------------------------ itens da conversa

// O Claude troca o caminho de imagem colado por "[Image #N]"; outros anexos vão como
// "Anexo: caminho". O servidor devolve em `anx` quais anexos a mensagem levou.
function separarAnexos(texto, anx) {
  const anexos = [...(anx || [])];
  const resto = [];
  for (const l of String(texto).replace(/\[Image #\d+\]/g, '').split('\n')) {
    const m = l.trim().match(/^(?:Anexo: )?\/\S+\/anexos\/(\d{4}-\d{2}-\d{2}\/[^\s/]+)$/);
    if (m) { if (!anexos.includes(m[1])) anexos.push(m[1]); continue; }
    const imgs = l.trim().match(/^Imagens:(.*)$/);
    if (imgs) {
      for (const c of imgs[1].trim().split(/\s+/)) {
        const r = c.match(/\/anexos\/(\d{4}-\d{2}-\d{2}\/[^\s/]+)$/);
        if (r && !anexos.includes(r[1])) anexos.push(r[1]);
      }
      continue;
    }
    if (l.trim() === '[anexo]') continue;
    resto.push(l);
  }
  return { texto: resto.join('\n').trim(), anexos };
}

function miniaturas(rels, urlsLocais) {
  const box = document.createElement('div');
  box.className = 'miniaturas';
  rels.forEach((rel, k) => {
    const nome = rel.split('/').pop();
    if (/\.(jpe?g|png|gif|webp|heic|avif)$/i.test(nome)) {
      const img = document.createElement('img');
      img.loading = 'lazy'; img.alt = nome;
      img.src = (urlsLocais && urlsLocais[k]) || `/api/anexo/${rel}`;
      box.appendChild(img);
    } else {
      const chip = document.createElement('span');
      chip.className = 'arquivo-chip';
      chip.innerHTML = ic('arquivo') + `<span>${esc(nome.replace(/^\d{6}-/, ''))}</span>`;
      box.appendChild(chip);
    }
  });
  return box;
}

// Sua mensagem: o ❯ do prompt na calha e o texto ao lado, como o CLI mostra.
function montarUsuario(texto, mini) {
  const div = document.createElement('div');
  div.className = 'msg-u';
  div.innerHTML = `<span class="calha">${ic('cursor')}</span>`;
  const corpo = document.createElement('div');
  corpo.className = 'corpo-u';
  if (texto) {
    const b = document.createElement('div');
    b.className = 'bolha';
    b.innerHTML = linkar(esc(texto));
    corpo.appendChild(b);
  }
  if (mini) corpo.appendChild(mini);
  const meta = document.createElement('div');
  meta.className = 'meta';
  corpo.appendChild(meta);
  div.appendChild(corpo);
  return { div, meta };
}

function elUsuario(it) {
  const { texto, anexos } = separarAnexos(it.txt, it.anx);
  const { div, meta } = montarUsuario(texto, anexos.length ? miniaturas(anexos) : null);
  const semMiniatura = it.img && !anexos.length ? `${it.img} imagem${it.img > 1 ? 's' : ''}` : '';
  meta.textContent = [hora(it.ts), it.fila ? 'enviada com o Claude ocupado' : '', semMiniatura]
    .filter(Boolean).join(' · ');
  return div;
}

function elAssistente(it) {
  const div = document.createElement('div');
  div.className = it.t === 'erro' ? 'msg-erro' : 'msg-a';
  div.innerHTML = '<span class="calha"></span>';
  const corpo = document.createElement('div');
  corpo.className = 'md';
  corpo.innerHTML = md(it.txt);
  div.appendChild(corpo);
  if (it.t === 'a') {
    const acoes = document.createElement('div');
    acoes.className = 'acoes-msg';
    const b = document.createElement('button');
    b.setAttribute('aria-label', 'Copiar a resposta');
    b.innerHTML = ic('copiar');
    b.addEventListener('click', () => copiar(it.txt, b));
    acoes.appendChild(b);
    div.appendChild(acoes);
  }
  return div;
}

function elSimples(classe, texto) {
  const d = document.createElement('div');
  d.className = classe;
  d.textContent = texto;
  return d;
}

function novoGrupo() {
  const g = document.createElement('div');
  g.className = 'atividade';
  const mais = document.createElement('button');
  mais.className = 'ativ-mais';
  mais.addEventListener('click', () => { g.classList.toggle('aberta'); atualizarGrupo(g); });
  g.appendChild(mais);
  return g;
}

function atualizarGrupo(g) {
  const n = g.querySelectorAll('.acao').length;
  g.classList.toggle('muitas', n > 3);
  g.querySelector('.ativ-mais').innerHTML = g.classList.contains('aberta')
    ? `${ic('recolher')}recolher ações` : `${ic('abrir')}mais ${n - 2} ações`;
}

function elFerramenta(it) {
  const a = document.createElement('div');
  a.className = 'acao';
  a.dataset.id = it.id;
  const linha = document.createElement('button');
  linha.className = 'acao-linha';
  linha.innerHTML = `<span class="bolinha"></span><span class="acao-txt"><span class="resumo">${esc(it.txt)}</span>` +
    (it.sub ? `<span class="acao-sub"><i class="galho"></i><span>${esc(it.sub)}</span></span>` : '') + '</span>';
  linha.addEventListener('click', () => abrirDetalhe(a));
  const det = document.createElement('div');
  det.className = 'acao-detalhe';
  det.hidden = true;
  a.append(linha, det);
  S.ferramentas.set(it.id, a);
  marcar(it.id);
  return a;
}

// Comando e saída como o CLI escreve: "❯ /model" e, embaixo, "⎿  Set model to …".
function elComando(txt) {
  const d = document.createElement('div');
  d.className = 'cli-cmd';
  d.innerHTML = `<span class="calha">${ic('cursor')}</span><span>${esc(txt)}</span>`;
  return d;
}

function elSaida(txt) {
  const d = document.createElement('div');
  d.className = 'cli-saida';
  const corpo = txt.includes('\n')
    ? `<pre class="cli-pre">${esc(txt)}</pre>` : `<span>${inline(txt)}</span>`;
  d.innerHTML = `<span class="calha"></span><div><i class="galho"></i>${corpo}</div>`;
  return d;
}

function elFimTurno(it) {
  const d = document.createElement('div');
  d.className = 'fim-turno';
  d.innerHTML = `<span class="calha">${ic('faisca')}</span>` +
    `<span>Worked for ${duracaoCli(it.ms)}${it.ts ? ' · done ' + hora(it.ts) : ''}</span>`;
  return d;
}

function marcar(id) {
  const a = S.ferramentas.get(id);
  if (!a) return;
  a.classList.remove('rodando', 'ok', 'erro');
  if (S.resultados.has(id)) a.classList.add(S.resultados.get(id) ? 'erro' : 'ok');
  else if (S.estado && S.estado.trabalhando) a.classList.add('rodando');
}

async function abrirDetalhe(a) {
  const det = a.querySelector('.acao-detalhe');
  if (!det.hidden) { det.hidden = true; a.classList.remove('aberta'); return; }
  det.hidden = false;
  a.classList.add('aberta');
  det.innerHTML = CARREGANDO;
  try {
    const d = await api('/api/saida/' + encodeURIComponent(a.dataset.id));
    det.innerHTML = '';
    for (const b of d.entrada) {
      if (!String(b.txt || '').trim()) continue;
      det.appendChild(blocoDetalhe(b.rotulo, b.txt, b.mono, b.tom));
    }
    if (!d.pronto) det.appendChild(blocoDetalhe('Saída', 'Ainda rodando…', false));
    else if (d.saida.trim() || !d.imagens.length) {
      det.appendChild(blocoDetalhe(d.erro ? 'Erro' : 'Saída', d.saida.trim() ? d.saida : '(sem saída)', true, d.erro ? 'falha' : ''));
    }
    if (d.imagens.length) {
      const box = document.createElement('div');
      box.className = 'det-bloco det-imagens';
      for (const src of d.imagens) { const img = document.createElement('img'); img.src = src; box.appendChild(img); }
      det.appendChild(box);
    }
  } catch (e) {
    det.innerHTML = `<div class="carregando">${esc(e.message)}</div>`;
  }
}

function blocoDetalhe(rotulo, texto, mono, tom) {
  const b = document.createElement('div');
  b.className = 'det-bloco' + (tom ? ' ' + tom : '');
  const topo = document.createElement('div');
  topo.className = 'det-rotulo';
  topo.innerHTML = `<span>${esc(rotulo)}</span>`;
  const bt = document.createElement('button');
  bt.className = 'copiar';
  bt.innerHTML = `${ic('copiar')}<span class="rot">copiar</span>`;
  bt.addEventListener('click', () => copiar(texto, bt));
  topo.appendChild(bt);
  const corpo = document.createElement(mono ? 'pre' : 'p');
  if (mono) corpo.className = 'bloco';
  corpo.textContent = texto;
  b.append(topo, corpo);
  return b;
}

function divisorDeDia(it) {
  const d = dia(it.ts);
  if (!d || d === S.ultimoDia) return null;
  S.ultimoDia = d;
  return elSimples('marco', d);
}

function renderizar(itens, noFim) {
  const frag = document.createDocumentFragment();
  let grupo = noFim && S.grupo && S.grupo === el.conversa.lastElementChild ? S.grupo : null;
  for (const it of itens) {
    if (it.t === 'r') { S.resultados.set(it.id, it.erro); marcar(it.id); continue; }
    if (it.t === 'f') {
      if (!grupo) { grupo = novoGrupo(); frag.appendChild(grupo); }
      grupo.appendChild(elFerramenta(it));
      atualizarGrupo(grupo);
      continue;
    }
    grupo = null;
    if (it.t === 'u' && noFim) {
      const div = divisorDeDia(it);
      if (div) frag.appendChild(div);
    }
    if (it.t === 'u') { frag.appendChild(elUsuario(it)); if (noFim) tirarPendente(it.txt); }
    else if (it.t === 'cmd') { frag.appendChild(elComando(it.txt)); if (noFim) tirarPendente(it.txt); }
    else if (it.t === 'a' || it.t === 'erro') frag.appendChild(elAssistente(it));
    else if (it.t === 'marco') frag.appendChild(elSimples('marco', it.txt));
    else if (it.t === 'fim') frag.appendChild(elFimTurno(it));
    else if (it.t === 'saida') frag.appendChild(elSaida(it.txt));
    else if (it.t === 'entrega') frag.appendChild(elEntrega(it));
  }
  if (noFim) {
    el.conversa.appendChild(frag);
    S.grupo = grupo;
  } else {
    el.conversa.insertBefore(frag, el.conversa.firstChild);
  }
  el.vazio.hidden = el.conversa.children.length > 0;
}

// ------------------------------------------------------------------ rolagem

const pertoDoFim = () => el.rolagem.scrollHeight - el.rolagem.scrollTop - el.rolagem.clientHeight < 140;
function rolarProFim(suave) {
  const r = el.rolagem;
  const fim = r.scrollHeight - r.clientHeight;
  // longe demais: pula o grosso na hora e anima só a última tela, senão a volta demora
  if (suave && fim - r.scrollTop > r.clientHeight * 1.5) r.scrollTop = fim - r.clientHeight;
  r.scrollTo({ top: r.scrollHeight, behavior: suave ? 'smooth' : 'auto' });
  S.novasPendentes = false;
  el.fim.hidden = true;
}

// Botão de voltar pro fim: aparece depois de subir mais de uma tela; com mensagem nova
// chegando enquanto você lê lá em cima, fica laranja e diz "Novas mensagens".
function atualizarBotaoFim() {
  const r = el.rolagem;
  const distancia = r.scrollHeight - r.scrollTop - r.clientHeight;
  if (distancia < 140) S.novasPendentes = false;
  el.fim.classList.toggle('novas', !!S.novasPendentes);
  el.fim.hidden = !(distancia > r.clientHeight || (S.novasPendentes && distancia >= 140));
}
let fimAgendado = false;
el.rolagem.addEventListener('scroll', () => {
  if (fimAgendado) return;
  fimAgendado = true;
  requestAnimationFrame(() => { fimAgendado = false; atualizarBotaoFim(); });
}, { passive: true });
el.fim.addEventListener('click', () => rolarProFim(true));

function anexarItens(itens) {
  const colado = pertoDoFim();
  renderizar(itens, true);
  S.total = itens[itens.length - 1].i + 1;
  if (colado) rolarProFim(false);
  else { S.novasPendentes = true; atualizarBotaoFim(); }
}

el.anteriores.addEventListener('click', async () => {
  const rotulo = el.anteriores.querySelector('span');
  el.anteriores.disabled = true;
  rotulo.textContent = 'Carregando…';
  try {
    const d = await api(`/api/conversa?antes=${S.inicio}&limite=150`);
    if ((d.estado.sessao || '') !== (S.sessao || '')) return carregar();
    const altura = el.rolagem.scrollHeight;
    renderizar(d.itens, false);
    el.rolagem.scrollTop += el.rolagem.scrollHeight - altura;
    S.inicio = d.inicio;
    el.anteriores.hidden = S.inicio === 0;
  } catch (e) {
    avisar(e.message, true);
  } finally {
    el.anteriores.disabled = false;
    rotulo.textContent = 'Carregar mensagens anteriores';
  }
});

// ------------------------------------------------------------------ estado da sessão

function aplicarEstado(e) {
  if (e.versao) {
    if (!S.versao) S.versao = e.versao;
    else if (e.versao !== S.versao) pedirRecarga();
  }
  S.estado = e;
  S.marca = e.marca;
  if (e.marca_tela) S.marcaTela = e.marca_tela;
  el.titulo.textContent = e.titulo || 'Claude';

  let classe = 'pronto', texto = 'pronto';
  if (!e.tmux) { classe = 'erro'; texto = 'sessão do tmux não existe'; }
  else if (!e.aberto) { classe = ''; texto = 'Claude fechado'; }
  else if (e.iniciando) { classe = 'trabalhando'; texto = 'abrindo o Claude'; }
  else if (e.pergunta) { classe = 'pergunta'; texto = 'esperando sua resposta'; }
  else if (e.trabalhando) { classe = 'trabalhando'; texto = 'trabalhando'; }
  marcarStatus(classe, texto + (e.pasta ? ` · ${e.pasta}` : ''));
  document.title = (e.pergunta ? 'Pergunta · ' : e.iniciando ? 'Abrindo · ' : e.trabalhando ? 'Trabalhando · ' : '') + (e.titulo || 'Claude');
  marcarFavicon(classe);

  if (!e.trabalhando) document.querySelectorAll('.acao.rodando').forEach((a) => a.classList.remove('rodando'));
  else S.ferramentas.forEach((a, id) => { if (!S.resultados.has(id)) a.classList.add('rodando'); });

  try {
    desenharPergunta(e.pergunta);
  } catch (erro) {
    console.error('painel: falha ao desenhar o menu', erro);
    S.pergAssinatura = null;
  }
  atualizarCompositor();
  if (S.telaAberta && typeof e.tela === 'string') desenharTela(e.tela, e.colunas, e.tela_html, e.links);
  el.btFecharClaude.hidden = !e.aberto;
  if (!el.gaveta.hidden) desenharSessoes();
  for (const p of S.pendentes) {
    if (p.entregue) p.meta.textContent = e.trabalhando ? 'na fila do Claude' : 'entregue';
  }
}

// O status mora na faísca da navbar (gira trabalhando, parada pronta); o texto fica pro leitor de tela e pro hover.
function marcarStatus(classe, texto) {
  el.ponto.className = 'ponto ' + classe;
  el.ponto.setAttribute('aria-label', texto);
  el.ponto.title = texto;
}

// Favicon com a faísca na cor do estado (aparece na aba do navegador do PC).
const COR_ESTADO = { pronto: '#d97757', trabalhando: '#d97757', pergunta: '#b1b9f9', erro: '#f2727f' };
let faviconCor = '';
function marcarFavicon(classe) {
  const cor = COR_ESTADO[classe] || '#85817a';
  if (cor === faviconCor) return;
  faviconCor = cor;
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="5" fill="#141413"/>' +
    `<path fill="${cor}" transform="translate(3 3) scale(.75)" d="${FAISCA_D}"/></svg>`;
  el.favicon.href = 'data:image/svg+xml,' + encodeURIComponent(svg);
}

function desenharPergunta(p) {
  const assinatura = p ? JSON.stringify(p) : '';
  if (assinatura === S.pergAssinatura) return;
  S.pergAssinatura = assinatura;
  el.pergunta.classList.remove('enviando');
  if (!p) { el.pergunta.hidden = true; el.pergForm.hidden = true; return; }
  el.pergunta.dataset.tipo = p.tipo;
  el.pergTexto.innerHTML = (p.blocos || []).map((b) => (b.t === 'cod' ? `<pre class="perg-cod">${esc(b.txt)}</pre>`
    : `<p${b.t === 'titulo' ? ' class="perg-tit"' : ''}>${linkar(esc(b.txt))}</p>`)).join('');
  el.pergOpcoes.innerHTML = '';
  if (p.tipo === 'lista') desenharLista(p);
  else if (p.tipo === 'regua') desenharRegua(p);
  else if (p.tipo === 'login') desenharLogin(p);
  else desenharLivre(p);
  // /effort (só a régua: tocar num nível já confirma) e /login (botão + campo) ficam sem as
  // dicas de tecla do CLI; o X no canto é o Esc.
  const cartaoProprio = p.tipo === 'regua' || p.tipo === 'login';
  $('#perg-dicas').hidden = cartaoProprio;
  el.pergFechar.hidden = !cartaoProprio;
  el.pergVerTela.hidden = cartaoProprio;
  if (cartaoProprio) el.pergForm.hidden = true;
  else desenharDicas(p);
  const estavaOculta = el.pergunta.hidden;
  el.pergunta.hidden = false;
  if (estavaOculta && pertoDoFim()) requestAnimationFrame(() => rolarProFim(false));
}

// Lista: cada opção como o CLI escreve (número, nome, descrição). O cursor (❯) é o do CLI:
// tocar numa opção leva o cursor até ela; tocar na que já está marcada confirma (Enter).
function desenharLista(p) {
  for (const o of p.opcoes) {
    const b = document.createElement('button');
    b.className = 'opcao' + (o.sel ? ' sel' : '');
    b.innerHTML = `<span class="cursor">${o.sel ? ic('cursor') : ''}</span>` +
      (p.numerado ? `<span class="num">${o.n}.</span>` : '') +
      (o.desc && o.desc.length <= 24 && !o.desc.includes(' · ')
        ? `<span class="op-txt">${esc(o.txt)}</span><span class="op-valor">${esc(o.desc)}</span>`
        : `<span class="op-txt">${esc(o.txt)}${o.desc ? `<small>${esc(o.desc)}</small>` : ''}</span>`);
    b.addEventListener('click', () => acaoMenu('opcao', { n: o.n, txt: o.txt }, p.assinatura));
    el.pergOpcoes.appendChild(b);
  }
  for (const n of p.notas || []) {
    const d = document.createElement('div');
    d.className = 'perg-nota';
    d.textContent = n;
    el.pergOpcoes.appendChild(d);
  }
}

// Régua (/effort): o ▲ do CLI vira um losango no trilho, cheio até o nível atual; tocar leva o losango até lá.
function desenharRegua(p) {
  if (p.extremos && p.extremos.length === 2) {
    el.pergOpcoes.insertAdjacentHTML('beforeend',
      `<div class="regua-extremos"><span>${esc(p.extremos[0])}</span><span>${esc(p.extremos[1])}</span></div>`);
  }
  const niveis = document.createElement('div');
  niveis.className = 'regua-niveis';
  p.niveis.forEach((n, k) => {
    const b = document.createElement('button');
    b.className = 'regua-nivel' + (k === p.atual ? ' sel' : k < p.atual ? ' cheio' : '');
    b.setAttribute('aria-pressed', String(k === p.atual));
    b.innerHTML = `<span class="regua-pino"></span><span>${esc(n)}</span>`;
    b.addEventListener('click', () => acaoMenu('nivel', { indice: k, confirmar: true }, p.assinatura));
    niveis.appendChild(b);
  });
  el.pergOpcoes.appendChild(niveis);
}

// /login: o CLI mostra um link de 6 linhas e espera o código colado. Aqui vira botão + campo.
function desenharLogin(p) {
  el.pergTexto.innerHTML = '<p class="perg-tit">Entrar na conta do Claude</p>';
  const c = document.createElement('div');
  c.className = 'login';
  c.innerHTML = '<p class="login-passo"><b>1</b>Abra a página de login e entre na conta do Claude.</p>' +
    `<div class="login-acoes"><a class="ent-bt principal" href="${esc(p.url)}" target="_blank" rel="noopener">` +
    `${ic('fora')}<span>Abrir página de login</span></a>` +
    `<button class="ent-bt" type="button">${ic('copiar')}<span class="rot">copiar</span></button></div>` +
    '<p class="login-passo"><b>2</b>A página mostra um código no fim. Copie e cole aqui:</p>' +
    '<form class="login-form"><input type="text" placeholder="Código" autocomplete="one-time-code" autocapitalize="off" ' +
    'autocorrect="off" spellcheck="false" enterkeyhint="send"><button class="tecla principal" type="submit">Enviar</button></form>';
  c.querySelector('button.ent-bt').addEventListener('click', (ev) => copiar(p.url, ev.currentTarget));
  c.querySelector('form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const campo = ev.currentTarget.querySelector('input');
    const codigo = campo.value.trim();
    if (!codigo) return;
    try {
      const d = await api('/api/digitar', { metodo: 'POST', corpo: { texto: codigo, enter: true } });
      campo.value = '';
      aplicarEstado(d.estado);
      acordar();
    } catch (e) {
      avisar(e.message, true);
    }
  });
  el.pergOpcoes.appendChild(c);
}

// Menu que o painel não conhece (/config, /rewind): a tela do CLI como está, com as cores.
function desenharLivre(p) {
  const pre = document.createElement('pre');
  pre.className = 'perg-livre';
  pre.innerHTML = (p.html && p.html.length ? p.html : String(p.texto || '').split('\n').map(esc)).join('\n');
  el.pergOpcoes.appendChild(pre);
}

// Botões com as dicas do próprio menu: [Enter] to confirm · [s] for this session only · [Esc] to cancel
function desenharDicas(p) {
  const caixa = $('#perg-dicas');
  caixa.innerHTML = '';
  const dicas = [...(p.dicas || [])];
  if (!dicas.some((d) => d.teclas.some((x) => x.tecla === 'digitar'))) {
    dicas.push({ teclas: [{ tecla: 'digitar', nome: 'Digitar' }], acao: '', legenda: '' });
  }
  for (const d of dicas) {
    const g = document.createElement('div');
    g.className = 'dica';
    if (d.legenda) g.insertAdjacentHTML('beforeend', `<span class="dica-legenda">${esc(d.legenda)}</span>`);
    for (const x of d.teclas) {
      const b = document.createElement('button');
      b.className = 'tecla' + (x.tecla === 'Enter' ? ' principal' : '');
      if (ROTULO_TECLA[x.tecla]) { b.innerHTML = ROTULO_TECLA[x.tecla]; b.setAttribute('aria-label', x.nome); }
      else b.textContent = x.nome;
      if (x.tecla === 'digitar') b.addEventListener('click', () => { el.pergForm.hidden = !el.pergForm.hidden; if (!el.pergForm.hidden) el.pergCampo.focus(); });
      else b.addEventListener('click', () => tecla(x.tecla));
      g.appendChild(b);
    }
    if (d.acao) g.insertAdjacentHTML('beforeend', `<span class="dica-acao">${esc(d.acao)}</span>`);
    caixa.appendChild(g);
  }
  caixa.appendChild(el.pergVerTela);
}

async function acaoMenu(acao, alvo, assinatura) {
  if (el.pergunta.classList.contains('enviando')) return;
  el.pergunta.classList.add('enviando');
  try {
    const d = await api('/api/menu', { metodo: 'POST', corpo: { acao, alvo, assinatura } });
    S.pergAssinatura = null;
    aplicarEstado(d.estado);
  } catch (e) {
    S.pergAssinatura = null;
    avisar(e.message, true);
  }
  el.pergunta.classList.remove('enviando');
  acordar();
}

// ------------------------------------------------------------------ compositor

function atualizarCompositor() {
  const e = S.estado || {};
  const subindo = S.anexos.some((a) => !a.pronto && !a.falhou);
  const temConteudo = el.texto.value.trim() || S.anexos.some((a) => a.pronto);
  let dica = 'Mensagem pro Claude';
  let bloqueado = false;
  if (e.tmux === false) { dica = 'Sessão do tmux não existe'; bloqueado = true; }
  else if (e.aberto === false) { dica = 'O Claude está fechado'; bloqueado = true; }
  else if (e.pergunta) { dica = 'Responda a pergunta acima'; bloqueado = true; }
  else if (e.iniciando) { dica = 'Abrindo o Claude…'; bloqueado = true; }
  else if (e.trabalhando) dica = 'Mensagem (vai pra fila)';
  el.texto.placeholder = dica;
  const fechado = e.tmux === false || e.aberto === false;
  el.compositor.hidden = !!e.pergunta || fechado;
  el.vazio.classList.toggle('discreto', !!e.pergunta || fechado);
  desenharFechado(e, fechado);
  if (el.compositor.hidden) el.sugestoes.hidden = true;
  el.texto.disabled = bloqueado && !el.texto.value;
  const parar = !bloqueado && e.trabalhando && !temConteudo && !subindo;
  el.enviar.classList.toggle('parar', !!parar);
  el.enviar.setAttribute('aria-label', parar ? 'Parar o Claude' : 'Enviar');
  el.enviar.disabled = !parar && (bloqueado || subindo || !temConteudo);
  const baixo = el.compositor.offsetHeight + (el.pergunta.hidden ? 0 : el.pergunta.offsetHeight + 8) +
    (el.fechado.hidden ? 0 : el.fechado.offsetHeight + 8);
  document.documentElement.style.setProperty('--alt-baixo', baixo + 'px');
}

function ajustarTexto() {
  el.texto.style.height = 'auto';
  const visivel = window.visualViewport ? window.visualViewport.height : window.innerHeight;
  el.texto.style.height = Math.min(el.texto.scrollHeight, Math.max(96, visivel * 0.35)) + 'px';
}

el.texto.addEventListener('input', () => {
  ajustarTexto();
  atualizarSugestoes();
  localStorage.setItem('painel.rascunho', el.texto.value);
  atualizarCompositor();
});
el.texto.addEventListener('keydown', (ev) => {
  if (!TOQUE && ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); acaoPrincipal(); }
});
el.enviar.addEventListener('click', acaoPrincipal);

async function acaoPrincipal() {
  if (el.enviar.disabled) return;
  if (el.enviar.classList.contains('parar')) {
    // Esc duas vezes seguidas abre o Rewind do CLI: um toque a mais no botão não pode virar o segundo Esc.
    if (Date.now() - (S.ultimoEsc || 0) < 2000) return;
    S.ultimoEsc = Date.now();
    return tecla('Escape', 'Pedi pro Claude parar');
  }
  const prontos = S.anexos.filter((a) => a.pronto);
  const texto = el.texto.value.trim();
  if (!texto && !prontos.length) return;
  if (!prontos.length && (texto === '/resume' || texto === '/exit')) {
    limparTexto();
    return texto === '/resume' ? abrirGaveta() : pedirFechar();
  }
  el.sugestoes.hidden = true;
  const ehComando = /^\/\S+/.test(texto) && !prontos.length;
  const pendente = ehComando ? criarComandoProvisorio(texto) : criarPendente(el.texto.value.trim(), prontos);
  el.texto.value = '';
  localStorage.removeItem('painel.rascunho');
  S.anexos = [];
  desenharAnexos();
  ajustarTexto();
  atualizarCompositor();
  rolarProFim(true);
  try {
    const d = await api('/api/enviar', { metodo: 'POST', corpo: { texto, anexos: prontos.map((a) => a.caminho) } });
    pendente.entregue = true;
    pendente.meta.textContent = d.estado.trabalhando ? 'na fila do Claude' : 'entregue';
    acordar();
  } catch (e) {
    pendente.el.remove();
    S.pendentes = S.pendentes.filter((p) => p !== pendente);
    el.texto.value = pendente.textoOriginal;
    S.anexos = prontos;
    desenharAnexos();
    ajustarTexto();
    atualizarCompositor();
    avisar(e.message, true);
  }
}

function criarComandoProvisorio(texto) {
  const div = elComando(texto);
  div.classList.add('provisorio');
  el.conversa.appendChild(div);
  el.vazio.hidden = true;
  const p = { el: div, meta: document.createElement('span'), texto: normal(texto), textoOriginal: texto, desde: Date.now(), entregue: false, comando: true };
  S.pendentes.push(p);
  return p;
}

function criarPendente(texto, anexos) {
  const mini = anexos.length ? miniaturas(anexos.map((a) => a.rel), anexos.map((a) => a.local)) : null;
  const { div, meta } = montarUsuario(texto, mini);
  div.classList.add('pendente');
  meta.textContent = 'enviando…';
  el.conversa.appendChild(div);
  el.vazio.hidden = true;
  const p = { el: div, meta, texto: normal(texto), textoOriginal: texto, desde: Date.now(), entregue: false };
  S.pendentes.push(p);
  return p;
}

function tirarPendente(textoChegou) {
  const alvo = normal(separarAnexos(textoChegou).texto);
  const cmd = S.pendentes.findIndex((p) => p.comando && (p.texto === alvo || p.texto.split(' ')[0] === alvo.split(' ')[0]));
  if (cmd >= 0 && alvo.startsWith('/')) { S.pendentes[cmd].el.remove(); S.pendentes.splice(cmd, 1); return; }
  const k = S.pendentes.findIndex((p) => !p.comando && (p.texto === alvo ||
    (p.texto && (alvo.includes(p.texto) || (alvo.length > 40 && p.texto.includes(alvo))))));
  if (k >= 0) { S.pendentes[k].el.remove(); S.pendentes.splice(k, 1); }
  // A conversa andou e a pendente não apareceu: o Claude mudou o texto (ex.: virou [Image #1]).
  S.pendentes = S.pendentes.filter((p) => !p.comando || Date.now() - p.desde < 600000);
}

// Régua do Claude (ex.: /effort): toca no nível, depois confirma como padrão ou só nesta sessão.
async function tecla(nome, msgOk) {
  try {
    const d = await api('/api/tecla', { metodo: 'POST', corpo: { tecla: nome } });
    if (msgOk) avisar(msgOk);
    aplicarEstado(d.estado);
    acordar();
  } catch (e) {
    el.pergunta.classList.remove('enviando');
    avisar(e.message, true);
  }
}

document.addEventListener('click', (ev) => {
  const b = ev.target.closest('[data-tecla]');
  if (b) { tecla(b.dataset.tecla); return; }
  const sessao = ev.target.closest('[data-sessao]');
  if (sessao) { acaoSessao(sessao.dataset.sessao); return; }
  const abrir = ev.target.closest('[data-abrir]');
  if (abrir) { if (abrir.dataset.abrir === 'tela') abrirTela(); else abrirGaveta(); return; }
  const fechar = ev.target.closest('[data-fechar]');
  if (fechar) { if (fechar.dataset.fechar === 'gaveta') fecharGaveta(); else if (S.fecharConfirma) S.fecharConfirma(); return; }
  const c = ev.target.closest('[data-copiar="pre"]');
  if (c) copiar(c.closest('.codigo').querySelector('pre').textContent, c);
});

el.pergForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const texto = el.pergCampo.value;
  if (!texto.trim()) return;
  try {
    const d = await api('/api/digitar', { metodo: 'POST', corpo: { texto, enter: false } });
    el.pergCampo.value = '';
    el.pergForm.hidden = true;
    aplicarEstado(d.estado);
    acordar();
  } catch (e) { avisar(e.message, true); }
});

// ------------------------------------------------------------------ anexos

el.anexar.addEventListener('click', () => el.arquivo.click());
el.arquivo.addEventListener('change', () => {
  for (const f of el.arquivo.files) subirAnexo(f);
  el.arquivo.value = '';
});

function subirAnexo(arquivo) {
  const a = { id: Math.random().toString(36).slice(2), nome: arquivo.name, tipo: arquivo.type, progresso: 0, pronto: false, falhou: false };
  if (arquivo.type.startsWith('image/')) a.local = URL.createObjectURL(arquivo);
  S.anexos.push(a);
  desenharAnexos();
  atualizarCompositor();
  const x = new XMLHttpRequest();
  a.xhr = x;
  x.open('PUT', '/api/anexo?nome=' + encodeURIComponent(arquivo.name || 'arquivo'));
  x.setRequestHeader('X-Painel', '1');
  x.upload.onprogress = (ev) => {
    if (!ev.lengthComputable) return;
    a.progresso = ev.loaded / ev.total;
    const barra = el.anexos.querySelector(`[data-id="${a.id}"] .progresso i`);
    if (barra) barra.style.width = (a.progresso * 100) + '%';
  };
  x.onload = () => {
    if (x.status === 200) {
      const r = JSON.parse(x.responseText);
      Object.assign(a, { pronto: true, caminho: r.caminho, rel: r.url.replace('/api/anexo/', '') });
    } else {
      a.falhou = true;
      let msg = `O envio de ${arquivo.name} falhou.`;
      try { msg = JSON.parse(x.responseText).erro || msg; } catch { /* sem json */ }
      avisar(msg, true);
    }
    desenharAnexos();
    atualizarCompositor();
  };
  x.onerror = () => { a.falhou = true; avisar(`Caiu a conexão enviando ${arquivo.name}.`, true); desenharAnexos(); atualizarCompositor(); };
  x.send(arquivo);
}

function desenharAnexos() {
  el.anexos.innerHTML = '';
  for (const a of S.anexos) {
    const d = document.createElement('div');
    d.className = 'anexo' + (a.pronto ? ' pronto' : '') + (a.falhou ? ' falhou' : '');
    d.dataset.id = a.id;
    if (a.local) { const img = document.createElement('img'); img.src = a.local; img.alt = a.nome; d.appendChild(img); }
    else d.insertAdjacentHTML('beforeend', ic('arquivo') + `<span class="ext">${esc((a.nome.split('.').pop() || 'arquivo').slice(0, 6).toLowerCase())}</span>`);
    d.insertAdjacentHTML('beforeend', `<div class="progresso"><i style="width:${a.progresso * 100}%"></i></div>`);
    const x = document.createElement('button');
    x.className = 'tirar';
    x.setAttribute('aria-label', 'Tirar anexo');
    x.innerHTML = ic('fechar');
    x.addEventListener('click', () => {
      if (a.xhr && !a.pronto) a.xhr.abort();
      S.anexos = S.anexos.filter((b) => b !== a);
      desenharAnexos();
      atualizarCompositor();
    });
    d.appendChild(x);
    el.anexos.appendChild(d);
  }
}

// ------------------------------------------------------------------ tela do terminal

function abrirTela() {
  S.telaAberta = true;
  el.folha.hidden = false;
  el.btTela.classList.add('ativo');
  S.marcaTela = '';
  acordar();
}
function fecharTela() {
  S.telaAberta = false;
  el.folha.hidden = true;
  el.btTela.classList.remove('ativo');
}
el.btTela.addEventListener('click', () => (S.telaAberta ? fecharTela() : abrirTela()));
el.pergVerTela.addEventListener('click', abrirTela);
el.pergFechar.addEventListener('click', () => { el.pergunta.classList.add('enviando'); tecla('Escape'); });
$('#folha-fechar').addEventListener('click', fecharTela);
$('#folha-fundo').addEventListener('click', fecharTela);

// Links que estão na tela do terminal, inteiros (o CLI quebra link comprido em várias linhas).
function desenharLinksTela(links) {
  const caixa = $('#tela-links');
  const chave = JSON.stringify(links || []);
  if (caixa.dataset.chave === chave) return;
  caixa.dataset.chave = chave;
  caixa.innerHTML = '';
  for (const url of links || []) {
    let host = url;
    try { host = new URL(url).host; } catch { /* fica o texto */ }
    const linha = document.createElement('div');
    linha.className = 'tela-link';
    linha.innerHTML = `${ic('link')}<span>${esc(host)}</span>` +
      `<a class="ent-bt" href="${esc(url)}" target="_blank" rel="noopener">${ic('fora')}<span>Abrir</span></a>` +
      `<button class="ent-bt" type="button" aria-label="Copiar o link">${ic('copiar')}</button>`;
    linha.querySelector('button').addEventListener('click', (ev) => copiar(url, ev.currentTarget));
    caixa.appendChild(linha);
  }
  caixa.hidden = !(links || []).length;
}

function desenharTela(texto, colunas, html, links) {
  desenharLinksTela(links);
  const largura = el.tela.clientWidth - 20;
  const tamanho = Math.max(7, Math.min(13, largura / ((colunas || 80) * 0.61)));
  el.tela.style.fontSize = tamanho.toFixed(2) + 'px';
  const noFim = el.tela.scrollHeight - el.tela.scrollTop - el.tela.clientHeight < 30;
  if (html && html.length) el.tela.innerHTML = html.join('\n');
  else el.tela.textContent = texto || '(tela vazia)';
  if (noFim) el.tela.scrollTop = el.tela.scrollHeight;
}

// ------------------------------------------------------------------ conversas e sessão

function limparTexto() {
  el.texto.value = '';
  localStorage.removeItem('painel.rascunho');
  el.sugestoes.hidden = true;
  ajustarTexto();
  atualizarCompositor();
}

function desenharFechado(e, fechado) {
  el.fechado.hidden = !fechado;
  if (!fechado) return;
  const semTmux = e.tmux === false;
  $('#fech-botoes').hidden = semTmux || !e.shell;
  $('#fech-outro').hidden = semTmux || !!e.shell;
  $('#fech-tmux').hidden = !semTmux;
  $('#fech-titulo').textContent = semTmux ? 'A sessão do terminal não existe' : 'O Claude está fechado';
  $('#fech-sub').textContent = semTmux ? 'Ela sobe sozinha quando o PC liga. Dá pra ligar agora por aqui.'
    : e.shell ? `As conversas ficam salvas. Pasta: ${e.pasta || '~'}`
      : 'O terminal está com outro programa aberto. Veja o que é pela tela.';
}

function confirmar(titulo, texto, sim = 'Confirmar') {
  return new Promise((resolve) => {
    $('#conf-titulo').textContent = titulo;
    $('#conf-texto').textContent = texto;
    $('#conf-sim').textContent = sim;
    const caixa = $('#confirma');
    caixa.hidden = false;
    const fim = (v) => {
      caixa.hidden = true;
      $('#conf-sim').onclick = $('#conf-nao').onclick = null;
      S.fecharConfirma = null;
      resolve(v);
    };
    $('#conf-sim').onclick = () => fim(true);
    $('#conf-nao').onclick = () => fim(false);
    S.fecharConfirma = () => fim(false);
  });
}

const MSG_SESSAO = {
  continuar: 'Abrindo o Claude…', nova: 'Começando uma conversa nova…', retomar: 'Abrindo a conversa…',
  fechar: 'Fechando o Claude…', ligar: 'Ligando a sessão…', reiniciar: 'Reiniciando o Claude…',
};

async function acaoSessao(acao, id) {
  if (document.body.classList.contains('ocupado')) return;
  if (acao === 'nova' && S.estado && S.estado.aberto &&
      !(await confirmar('Começar uma conversa nova?', 'A conversa atual fica salva na lista de conversas.', 'Começar'))) return;
  document.body.classList.add('ocupado');
  avisar(MSG_SESSAO[acao] || 'Um instante…', false, 20000);
  try {
    const d = await api('/api/sessao', { metodo: 'POST', corpo: { acao, id: id || '' } });
    fecharGaveta();
    aplicarEstado(d.estado);
    avisar(acao === 'fechar' ? 'Claude fechado. A conversa ficou salva.' : 'Pronto');
  } catch (e) {
    avisar(e.message, true);
  } finally {
    document.body.classList.remove('ocupado');
    acordar();
  }
}

async function pedirFechar() {
  if (await confirmar('Fechar o Claude?', 'A conversa fica salva. Você reabre por aqui quando quiser.', 'Fechar')) {
    acaoSessao('fechar');
  }
}
el.btFecharClaude.addEventListener('click', pedirFechar);
el.btConversas.addEventListener('click', () => abrirGaveta());

async function abrirGaveta(aba = 'conversas') {
  el.gaveta.hidden = false;
  trocarAba(aba);
  if (aba !== 'config') checarVersao();  // a marquinha na aba Configurações quando tem versão nova
  el.busca.value = '';
  el.btFecharClaude.hidden = !(S.estado && S.estado.aberto);
  if (S.sessoes.length) desenharSessoes();
  else el.listaSessoes.innerHTML = CARREGANDO;
  try {
    S.sessoes = (await api('/api/sessoes')).sessoes;
    desenharSessoes();
  } catch (e) {
    el.listaSessoes.innerHTML = `<div class="lista-vazia">${esc(e.message)}</div>`;
  }
}
function fecharGaveta() { el.gaveta.hidden = true; }

function quandoRelativo(ms) {
  const s = (Date.now() - ms) / 1000;
  if (s < 60) return 'agora';
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  if (s < 172800) return 'ontem';
  return new Date(ms).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
}

function desenharSessoes() {
  const termo = normal(el.busca.value).toLowerCase();
  const atual = S.estado && S.estado.aberto ? S.estado.sessao : null;
  const itens = S.sessoes.filter((s) => !termo || `${s.titulo} ${s.pasta} ${s.ultima}`.toLowerCase().includes(termo));
  el.listaSessoes.innerHTML = '';
  if (!itens.length) {
    el.listaSessoes.innerHTML = `<div class="lista-vazia">${termo ? 'Nenhuma conversa com esse termo.' : 'Nenhuma conversa salva.'}</div>`;
    return;
  }
  for (const s of itens) {
    const ehAtual = s.id === atual;
    const b = document.createElement('button');
    b.className = 'sessao' + (ehAtual ? ' atual' : '');
    b.innerHTML = `<div class="s-linha1"><span class="s-titulo">${esc(s.titulo)}</span>` +
      (ehAtual ? '<span class="s-selo">aberta</span>' : s.outro ? '<span class="s-selo outro">em outro terminal</span>'
        : `<span class="s-quando">${quandoRelativo(s.quando)}</span>`) + '</div>' +
      `<div class="s-linha2"><span class="s-pasta">${esc(s.pasta || '?')}</span>${s.ultima ? ' · ' + esc(s.ultima) : ''}</div>`;
    b.addEventListener('click', () => escolherSessao(s, ehAtual));
    el.listaSessoes.appendChild(b);
  }
}
el.busca.addEventListener('input', desenharSessoes);

async function escolherSessao(s, ehAtual) {
  if (ehAtual) return fecharGaveta();
  const aberto = S.estado && S.estado.aberto;
  const texto = aberto ? `O Claude fecha a conversa atual (ela fica salva) e abre “${s.titulo}”.`
    : `Abre “${s.titulo}” no Claude.`;
  if (await confirmar('Abrir esta conversa?', texto, 'Abrir')) acaoSessao('retomar', s.id);
}

// ------------------------------------------------------------------ entregas (bin/entregar)
// O que o Claude manda pro celular: cartão na conversa e lista na aba Arquivos da gaveta.

const urlEntrega = (it, extra = '') => `/api/entrega/${encodeURIComponent(it.id)}${extra}`;

function tamanhoHumano(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return `${n} B`;
  const un = ['KB', 'MB', 'GB'];
  let k = -1;
  do { n /= 1024; k++; } while (n >= 1024 && k < 2);
  return `${n.toFixed(n < 10 ? 1 : 0).replace('.', ',')} ${un[k]}`;
}
const minutos = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

function metaEntrega(it) {
  if (it.tipo === 'link') return it.url;
  return [it.tipo === 'arquivo' ? (it.nome.split('.').pop() || 'arquivo').toLowerCase() : it.tipo,
    tamanhoHumano(it.tamanho), it.dur ? minutos(it.dur) : ''].filter(Boolean).join(' · ');
}

const podeSalvar = (it) => (it.tipo === 'imagem' || it.tipo === 'video') && it.tamanho < 300 * 1024 * 1024;

// Salvar = folha de compartilhar do iPhone ("Salvar Imagem"/"Salvar Vídeo" vão pro Fotos).
// O arquivo vem inteiro antes; se o Safari achar que o toque "esfriou" no download, o segundo toque compartilha.
async function salvarEntrega(it, botao) {
  const rotulo = botao.querySelector('.rot');
  try {
    if (!botao.arquivo) {
      if (rotulo) rotulo.textContent = 'Preparando…';
      const r = await fetch(urlEntrega(it), { cache: 'force-cache' });
      if (!r.ok) throw new Error('O arquivo não veio do PC.');
      botao.arquivo = new File([await r.blob()], it.nome, { type: it.mime || 'application/octet-stream' });
    }
    if (!navigator.canShare || !navigator.canShare({ files: [botao.arquivo] })) {
      location.href = urlEntrega(it, '?baixar=1');
    } else {
      await navigator.share({ files: [botao.arquivo] });
    }
    if (rotulo) rotulo.textContent = 'Salvar';
  } catch (e) {
    if (e.name === 'NotAllowedError') { if (rotulo) rotulo.textContent = 'Tocar pra salvar'; return; }
    if (rotulo) rotulo.textContent = 'Salvar';
    if (e.name !== 'AbortError') avisar(e.message || 'Não deu pra salvar.', true);
  }
}

function botoesEntrega(it, caixa) {
  const add = (html, classe, acao, href) => {
    const b = document.createElement(href ? 'a' : 'button');
    b.className = 'ent-bt' + (classe ? ' ' + classe : '');
    b.innerHTML = html;
    if (href) {
      b.href = href;
      if (acao === 'download') b.setAttribute('download', it.nome);
      else { b.target = '_blank'; b.rel = 'noopener'; }
    } else b.addEventListener('click', (ev) => { ev.stopPropagation(); acao(b); });
    caixa.appendChild(b);
  };
  if (it.tipo === 'link') return add(`${ic('fora')}<span class="rot">Abrir</span>`, 'principal', 'target', it.url);
  if (podeSalvar(it)) add(`${ic('salvar')}<span class="rot">Salvar</span>`, 'principal', (b) => salvarEntrega(it, b));
  if (it.tipo === 'pdf' || it.tipo === 'arquivo') add(`${ic('fora')}<span class="rot">Abrir</span>`, '', 'target', urlEntrega(it));
  add(`${ic('baixar')}<span class="rot">Baixar</span>`, podeSalvar(it) || it.tipo === 'pdf' ? '' : 'principal', 'download', urlEntrega(it, '?baixar=1'));
}

function cartaoEntrega(it) {
  const c = document.createElement('div');
  c.className = 'ent-card' + (it.faltando ? ' faltando' : '');
  if (it.faltando) {
    c.innerHTML = `<div class="ent-arquivo">${ic('arquivo')}<div class="ent-txt"><b>${esc(it.nome || 'Arquivo')}</b><small>não está mais no PC</small></div></div>`;
    return c;
  }
  if (it.legenda) c.insertAdjacentHTML('beforeend', `<div class="ent-legenda">${linkar(esc(it.legenda))}</div>`);
  const proporcao = it.larg && it.alt ? `aspect-ratio:${it.larg}/${it.alt}` : '';
  if (it.tipo === 'imagem') {
    const b = document.createElement('button');
    b.className = 'ent-midia';
    b.setAttribute('aria-label', `Ver ${it.nome}`);
    b.innerHTML = `<img loading="lazy" alt="" style="${proporcao}" src="${urlEntrega(it, it.previa ? '/previa' : '')}">`;
    b.addEventListener('click', () => abrirVisor(it));
    c.appendChild(b);
  } else if (it.tipo === 'video') {
    c.insertAdjacentHTML('beforeend', `<video class="ent-video" controls playsinline preload="none" style="${proporcao}"` +
      `${it.previa ? ` poster="${urlEntrega(it, '/previa')}"` : ''} src="${urlEntrega(it)}"></video>`);
  } else if (it.tipo === 'audio') {
    c.insertAdjacentHTML('beforeend', `<audio class="ent-audio" controls preload="none" src="${urlEntrega(it)}"></audio>`);
  } else {
    const icone = it.tipo === 'link' ? 'link' : 'arquivo';
    const titulo = it.tipo === 'link' ? (it.nome || it.url) : it.nome;
    c.insertAdjacentHTML('beforeend', `<div class="ent-arquivo">${ic(icone)}<div class="ent-txt"><b>${esc(titulo)}</b>` +
      `<small>${esc(metaEntrega(it))}</small></div></div>`);
  }
  const rodape = document.createElement('div');
  rodape.className = 'ent-rodape';
  if (it.tipo === 'imagem' || it.tipo === 'video' || it.tipo === 'audio') {
    rodape.insertAdjacentHTML('beforeend', `<span class="ent-meta">${esc(it.nome)} · ${esc(metaEntrega(it))}</span>`);
  } else rodape.insertAdjacentHTML('beforeend', '<span class="ent-meta"></span>');
  botoesEntrega(it, rodape);
  c.appendChild(rodape);
  return c;
}

function elEntrega(it) {
  const d = document.createElement('div');
  d.className = 'entrega';
  d.innerHTML = `<span class="calha">${ic('baixar')}</span>`;
  const lista = document.createElement('div');
  lista.className = 'ent-lista';
  const itens = it.itens || [];
  // a mesma legenda em todos (um --legenda pra vários arquivos) aparece uma vez só, em cima
  const comum = itens.length > 1 && itens.every((x) => x.legenda && x.legenda === itens[0].legenda) ? itens[0].legenda : '';
  if (comum) lista.insertAdjacentHTML('beforeend', `<div class="ent-legenda-grupo">${linkar(esc(comum))}</div>`);
  for (const x of itens) lista.appendChild(cartaoEntrega(comum ? { ...x, legenda: '' } : x));
  d.appendChild(lista);
  return d;
}

function abrirVisor(it) {
  el.visorNome.textContent = it.nome;
  el.visorCorpo.innerHTML = it.tipo === 'video'
    ? `<video controls playsinline autoplay src="${urlEntrega(it)}"></video>`
    : it.tipo === 'audio' ? `<audio controls autoplay src="${urlEntrega(it)}"></audio>`
      : `<img alt="${esc(it.nome)}" src="${urlEntrega(it)}">`;
  el.visorCorpo.scrollTop = 0;
  el.visorAcoes.innerHTML = '';
  botoesEntrega(it, el.visorAcoes);
  el.visor.hidden = false;
}
function fecharVisor() {
  el.visor.hidden = true;
  el.visorCorpo.innerHTML = '';  // para o vídeo
}
$('#visor-fechar').addEventListener('click', fecharVisor);

function abrirEntrega(it) {
  if (it.faltando) return;
  if (it.tipo === 'imagem' || it.tipo === 'video' || it.tipo === 'audio') return abrirVisor(it);
  window.open(it.tipo === 'link' ? it.url : urlEntrega(it), '_blank', 'noopener');
}

async function desenharEntregas() {
  if (!el.listaEntregas.children.length) el.listaEntregas.innerHTML = CARREGANDO;
  let lista;
  try {
    lista = (await api('/api/entregas')).entregas;
  } catch (e) {
    el.listaEntregas.innerHTML = `<div class="lista-vazia">${esc(e.message)}</div>`;
    return;
  }
  el.listaEntregas.innerHTML = lista.length ? ''
    : '<div class="lista-vazia">Nada entregue ainda. Peça um print, vídeo, arquivo ou link e ele aparece aqui.</div>';
  for (const it of lista) {
    const linha = document.createElement('div');
    linha.className = 'ent-linha' + (it.faltando ? ' faltando' : '');
    const miniatura = it.tipo === 'imagem' ? urlEntrega(it, it.previa ? '/previa' : '')
      : it.tipo === 'video' && it.previa ? urlEntrega(it, '/previa') : '';
    const abrir = document.createElement('button');
    abrir.className = 'ent-abrir';
    abrir.innerHTML = `<span class="ent-mini">${miniatura && !it.faltando ? `<img loading="lazy" alt="" src="${miniatura}">`
      : ic(it.tipo === 'link' ? 'link' : 'arquivo')}</span>` +
      `<span class="ent-txt"><b>${esc(it.tipo === 'link' ? it.legenda || it.nome : it.nome)}</b>` +
      `<small>${esc(it.faltando ? 'não está mais no PC' : `${metaEntrega(it)} · ${quandoRelativo(it.quando)}`)}</small></span>`;
    abrir.addEventListener('click', () => abrirEntrega(it));
    linha.appendChild(abrir);
    if (!it.faltando) {
      const b = document.createElement(podeSalvar(it) ? 'button' : 'a');
      b.className = 'bt-icone ent-acao';
      if (podeSalvar(it)) {
        b.setAttribute('aria-label', 'Salvar');
        b.innerHTML = ic('salvar');
        b.addEventListener('click', () => salvarEntrega(it, b));
      } else {
        b.setAttribute('aria-label', it.tipo === 'link' ? 'Abrir' : 'Baixar');
        b.innerHTML = ic(it.tipo === 'link' ? 'fora' : 'baixar');
        b.href = it.tipo === 'link' ? it.url : urlEntrega(it, '?baixar=1');
        if (it.tipo === 'link') { b.target = '_blank'; b.rel = 'noopener'; } else b.setAttribute('download', it.nome);
      }
      linha.appendChild(b);
    }
    el.listaEntregas.appendChild(linha);
  }
}

function trocarAba(aba) {
  document.querySelectorAll('.aba').forEach((b) => b.classList.toggle('ativa', b.dataset.aba === aba));
  $('#aba-conversas').hidden = aba !== 'conversas';
  $('#aba-arquivos').hidden = aba !== 'arquivos';
  $('#aba-config').hidden = aba !== 'config';
  if (aba === 'arquivos') desenharEntregas();
  if (aba === 'config') { desenharPush(); checarVersao(); }
}
document.querySelectorAll('.aba').forEach((b) => b.addEventListener('click', () => trocarAba(b.dataset.aba)));

// ------------------------------------------------------------------ notificações (Web Push)
// O iPhone só recebe notificação de web app aberto pela Tela de Início (iOS 16.4+). Quem decide
// quando avisar é o servidor (fim de turno, pergunta nova, sem ninguém olhando); aqui só liga.

const PUSH = {
  suportado: 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window,
  instalado: navigator.standalone === true || matchMedia('(display-mode: standalone)').matches,
  reg: null, chave: '', inscrito: false, prefs: { fim: true, pergunta: true },
};
const IOS = /iPhone|iPad|iPod/.test(navigator.userAgent);

function chaveBytes(t) {
  const s = atob(t.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (t.length % 4)) % 4));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}

function estadoPush() {
  if (!PUSH.suportado) return IOS && !PUSH.instalado ? 'instalar' : 'sem-suporte';
  if (Notification.permission === 'denied') return 'bloqueado';
  return PUSH.inscrito && Notification.permission === 'granted' ? 'ligado' : 'desligado';
}

const TEXTO_PUSH = {
  ligado: 'Ligadas', desligado: 'Desligadas',
  bloqueado: 'Bloqueadas: libere em Ajustes › Notificações › Claude',
  instalar: 'Abra o painel pelo ícone da Tela de Início pra ligar',
  'sem-suporte': 'Este navegador não recebe notificação',
};

function desenharPush() {
  const st = estadoPush();
  const ligado = st === 'ligado';
  const chave = $('#cfg-push');
  chave.setAttribute('aria-checked', String(ligado));
  chave.disabled = st === 'bloqueado' || st === 'instalar' || st === 'sem-suporte';
  $('#cfg-push-estado').textContent = TEXTO_PUSH[st];
  for (const tipo of ['fim', 'pergunta']) {
    const b = $(`#cfg-${tipo}`);
    b.setAttribute('aria-checked', String(PUSH.prefs[tipo] !== false));
    b.disabled = !ligado;
  }
  $('#aviso-push').hidden = st !== 'desligado' || localStorage.getItem('painel.push-dispensado') === '1';
}

async function iniciarPush() {
  if ('serviceWorker' in navigator) {
    try { PUSH.reg = await navigator.serviceWorker.register('/sw.js'); } catch (e) { console.warn('painel: service worker', e); }
  }
  if (PUSH.reg && PUSH.suportado) {
    try { PUSH.inscrito = !!(await PUSH.reg.pushManager.getSubscription()); } catch { /* sem inscrição */ }
    try {
      const d = await api('/api/push/chave');
      PUSH.chave = d.chave;
      PUSH.prefs = d.prefs || PUSH.prefs;
    } catch { /* busca de novo ao ativar */ }
  }
  if (navigator.clearAppBadge) navigator.clearAppBadge().catch(() => {});
  desenharPush();
}

async function ativarPush() {
  // no iPhone o pedido de permissão tem que vir logo depois do toque, antes de qualquer espera
  const permissao = await Notification.requestPermission();
  if (permissao !== 'granted') return desenharPush();
  try {
    if (!PUSH.chave) PUSH.chave = (await api('/api/push/chave')).chave;
    const reg = PUSH.reg || await navigator.serviceWorker.ready;
    const insc = (await reg.pushManager.getSubscription()) ||
      await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: chaveBytes(PUSH.chave) });
    await api('/api/push/inscrever', { metodo: 'POST', corpo: { inscricao: insc.toJSON() } });
    PUSH.inscrito = true;
    avisar('Notificações ligadas. Mandei uma de teste.');
  } catch (e) {
    avisar(e.message || 'Não deu pra ligar as notificações.', true);
  }
  desenharPush();
}

async function desativarPush() {
  try {
    const reg = PUSH.reg || await navigator.serviceWorker.ready;
    const insc = await reg.pushManager.getSubscription();
    if (insc) {
      await api('/api/push/sair', { metodo: 'POST', corpo: { endpoint: insc.endpoint } });
      await insc.unsubscribe();
    }
    PUSH.inscrito = false;
    avisar('Notificações desligadas neste iPhone.');
  } catch (e) {
    avisar(e.message || 'Não deu pra desligar.', true);
  }
  desenharPush();
}

$('#cfg-push').addEventListener('click', () => (estadoPush() === 'ligado' ? desativarPush() : ativarPush()));
for (const tipo of ['fim', 'pergunta']) {
  $(`#cfg-${tipo}`).addEventListener('click', async () => {
    const antes = PUSH.prefs[tipo] !== false;
    PUSH.prefs = { ...PUSH.prefs, [tipo]: !antes };
    desenharPush();
    try {
      PUSH.prefs = (await api('/api/push/prefs', { metodo: 'POST', corpo: PUSH.prefs })).prefs || PUSH.prefs;
    } catch (e) {
      PUSH.prefs = { ...PUSH.prefs, [tipo]: antes };
      avisar(e.message, true);
    }
    desenharPush();
  });
}
// ------------------------------------------------------------------ Claude Code (versão)
// O Claude se atualiza sozinho, mas o que já está aberto segue na versão antiga até reiniciar.

const VERSAO = { em_uso: '', instalada: '', aberto: false, atualizar: false };

async function checarVersao() {
  try { Object.assign(VERSAO, await api('/api/claude')); } catch { return; }
  desenharVersao();
}

function desenharVersao() {
  const v = VERSAO;
  $('#cfg-versao').textContent = !v.em_uso ? (v.aberto ? 'Não deu pra ler a versão' : 'Claude fechado')
    : v.atualizar ? `A ${v.instalada} já está instalada` : 'A mais recente instalada';
  $('#cfg-versao-num').textContent = v.em_uso || '';
  const b = $('#cfg-reiniciar');
  b.disabled = !v.aberto;
  b.classList.toggle('destaque', v.atualizar);
  $('#cfg-reiniciar-txt').textContent = v.atualizar ? `Passa pra ${v.instalada} e volta nesta conversa`
    : 'Fecha e abre de novo nesta conversa';
  document.querySelector('.aba[data-aba="config"]').classList.toggle('tem-aviso', v.atualizar);
}

$('#cfg-reiniciar').addEventListener('click', async () => {
  if (!(await confirmar('Reiniciar o Claude?', 'Ele fecha e abre de novo nesta mesma conversa. Nada se perde.', 'Reiniciar'))) return;
  await acaoSessao('reiniciar');
  checarVersao();
});
$('#bt-push-ativar').addEventListener('click', ativarPush);
$('#bt-push-fechar').addEventListener('click', () => { localStorage.setItem('painel.push-dispensado', '1'); desenharPush(); });

// Painel foi pro fundo (tela bloqueada, outro app): o PC volta a avisar na hora, sem esperar.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    fetch('/api/push/oculto', { method: 'POST', keepalive: true, body: '{}',
      headers: { 'X-Painel': '1', 'Content-Type': 'application/json' } }).catch(() => {});
  } else if (navigator.clearAppBadge) navigator.clearAppBadge().catch(() => {});
});

// ------------------------------------------------------------------ comandos com "/"

async function carregarComandos() {
  try { S.comandos = (await api('/api/comandos')).comandos; } catch { /* sem lista, digita na mão */ }
}

function atualizarSugestoes() {
  const t = el.texto.value;
  if (!/^\/[\w:.-]*$/.test(t) || !S.comandos.length || el.compositor.hidden) { el.sugestoes.hidden = true; return; }
  const termo = t.toLowerCase();
  const comeca = S.comandos.filter((c) => c.cmd.startsWith(termo));
  const contem = termo.length > 1 ? S.comandos.filter((c) => !c.cmd.startsWith(termo) && c.cmd.includes(termo.slice(1))) : [];
  const lista = [...comeca, ...contem];
  if (!lista.length || (lista.length === 1 && lista[0].cmd === termo && !lista[0].arg)) { el.sugestoes.hidden = true; return; }
  el.sugestoes.innerHTML = '';
  for (const c of lista) {
    const b = document.createElement('button');
    b.className = 'sug';
    b.setAttribute('role', 'option');
    b.innerHTML = `<span class="cmd">${esc(c.cmd)}</span><span class="desc">${esc(c.desc)}</span>` +
      (c.skill ? '<span class="tag">skill</span>' : '');
    b.addEventListener('pointerdown', (ev) => ev.preventDefault()); // não tira o foco nem fecha o teclado
    b.addEventListener('click', () => usarComando(c));
    el.sugestoes.appendChild(b);
  }
  el.sugestoes.hidden = false;
}

function usarComando(c) {
  el.sugestoes.hidden = true;
  if (c.cmd === '/resume' || c.cmd === '/exit') {
    limparTexto();
    return c.cmd === '/resume' ? abrirGaveta() : pedirFechar();
  }
  if (!c.arg) {  // sem argumento: já manda, em vez de só preencher a caixa
    el.texto.value = c.cmd;
    atualizarCompositor();
    return acaoPrincipal();
  }
  el.texto.value = c.cmd + ' ';
  localStorage.setItem('painel.rascunho', el.texto.value);
  ajustarTexto();
  atualizarCompositor();
  el.texto.focus();
}

function pedirRecarga() {
  const ocupado = el.texto.value.trim() || S.anexos.length || !el.gaveta.hidden || !$('#confirma').hidden || !el.pergForm.hidden ||
    !el.visor.hidden;
  if (!ocupado) return location.reload();
  if (!S.avisouVersao) { S.avisouVersao = true; avisar('O painel foi atualizado. Ele recarrega quando a caixa estiver vazia.', false, 6000); }
  setTimeout(pedirRecarga, 3000);
}

// ------------------------------------------------------------------ sincronização

function mostrarRede(ok) { el.rede.hidden = ok; }
function acordar() { if (S.ctrl) S.ctrl.abort(); }
$('#bt-reconectar').addEventListener('click', () => { S.falhas = 0; S.tentarJa?.(); acordar(); });

async function carregar() {
  const d = await api('/api/conversa' + (S.telaAberta ? '?tela=1' : ''));
  S.sessao = d.estado.sessao || '';
  S.inicio = d.inicio;
  S.total = d.inicio + d.itens.length;
  S.ferramentas.clear();
  S.resultados.clear();
  S.grupo = null;
  S.ultimoDia = '';
  S.pergAssinatura = null;
  el.conversa.innerHTML = '';
  S.estado = d.estado;
  renderizar(d.itens, true);
  aplicarEstado(d.estado);
  for (const p of S.pendentes) if (!p.comando) el.conversa.appendChild(p.el);
  el.anteriores.hidden = S.inicio === 0;
  rolarProFim(false);
  S.carregado = true;
}

async function ciclo() {
  for (;;) {
    if (document.hidden) {
      await new Promise((r) => document.addEventListener('visibilitychange', r, { once: true }));
      continue;
    }
    S.ctrl = new AbortController();
    const q = new URLSearchParams({ sessao: S.sessao || '', desde: String(S.total), marca: S.marca || '' });
    if (S.telaAberta) { q.set('tela', '1'); q.set('marca_tela', S.marcaTela || ''); }
    try {
      const d = await api('/api/eventos?' + q, { sinal: S.ctrl.signal });
      S.falhas = 0;
      mostrarRede(true);
      if (d.reiniciar) { await carregar(); continue; }
      if (d.itens && d.itens.length) anexarItens(d.itens);
      aplicarEstado(d.estado);
    } catch (e) {
      if (e.name === 'AbortError') continue;
      S.falhas++;
      if (S.falhas >= 2) mostrarRede(false);
      await dormir(Math.min(10000, 800 * 2 ** S.falhas));
    }
  }
}

document.addEventListener('visibilitychange', () => { if (document.hidden) acordar(); });

// No iPhone o teclado não encolhe a página; a altura útil vem do visualViewport.
function ajustarAltura() {
  const vv = window.visualViewport;
  const colado = pertoDoFim();
  document.documentElement.style.setProperty('--altura', (vv ? vv.height : window.innerHeight) + 'px');
  if (vv) window.scrollTo(0, 0);
  if (colado) rolarProFim(false);
  atualizarCompositor();
}
if (window.visualViewport) {
  visualViewport.addEventListener('resize', ajustarAltura);
  visualViewport.addEventListener('scroll', () => window.scrollTo(0, 0));
}
window.addEventListener('resize', ajustarAltura);

async function iniciar() {
  ajustarAltura();
  iniciarPush();
  const rascunho = localStorage.getItem('painel.rascunho');
  if (rascunho && !el.texto.value) { el.texto.value = rascunho; ajustarTexto(); }
  for (;;) {
    try {
      await carregar();
      mostrarRede(true);
      carregarComandos();
      checarVersao();
      break;
    } catch (e) {
      mostrarRede(false);
      marcarStatus('erro', e.status === 403 ? 'sem permissão' : 'sem conexão');
      if (e.status === 403) el.titulo.textContent = 'Sem permissão';
      if (e.status === 403) return;
      await new Promise((r) => { S.tentarJa = r; setTimeout(r, 3000); });
    }
  }
  ciclo();
}

iniciar();
