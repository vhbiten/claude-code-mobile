#!/usr/bin/env python3
"""Painel do Claude pro celular: a conversa inteira da sessão do tmux + prompt, anexo e teclas.

    painel-servidor.py [porta-local]        (padrão 8481; o install.sh publica na 8445 da tailnet)

Só atende pedidos que chegam pela Tailscale (tailscale serve) com o login do dono
do PC. Com o modo automático do Claude, quem manda prompt aqui manda no PC, então
qualquer dúvida na identidade vira recusa.

PAINEL_TMUX muda a sessão do tmux alvo (padrão "claude"); os testes usam outra.
PAINEL_CLAUDE é o comando que abre o Claude no shell (padrão "claude").
PAINEL_PORTA_TS é a porta da tailnet (padrão 8445); PAINEL_PASTA, a pasta onde o Claude abre.
"""

import hashlib
import html as html_lib
import json
import mimetypes
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

RAIZ = Path(__file__).resolve().parent.parent  # a pasta do projeto
ESTATICO = Path(os.environ.get("PAINEL_ESTATICO", RAIZ / "painel"))  # outra pasta só pra teste
ANEXOS = RAIZ / "anexos"
ENTREGAS = Path(os.environ.get("PAINEL_ENTREGAS", RAIZ / "entregas"))  # o que o Claude entrega pro celular (bin/entregar)
CLAUDE = Path.home() / ".claude"
ALVO = os.environ.get("PAINEL_TMUX", "claude")
CMD_CLAUDE = os.environ.get("PAINEL_CLAUDE", "claude")
PASTA_INICIAL = os.environ.get("PAINEL_PASTA", str(Path.home()))
SHELLS = {"zsh", "bash", "sh", "fish"}
SHELL_LOGIN = os.environ.get("SHELL", "/bin/bash")  # o shell que roda o Claude dentro do tmux
ID_SESSAO = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PORTA = int(sys.argv[1]) if len(sys.argv) > 1 else 8481
PORTA_TS = int(os.environ.get("PAINEL_PORTA_TS", "8445"))  # outra porta só pra teste
LIMITE_ANEXO = 2 * 1024**3
ESPERA_MAX = 25  # segundos que um /api/eventos segura a resposta esperando novidade
PRIMEIROS = 150  # itens mandados na abertura; o resto vem em "carregar anteriores"

ARQUIVOS_ESTATICOS = {
    "/": "index.html",
    "/app.css": "app.css",
    "/app.js": "app.js",
    "/manifest.webmanifest": "manifest.webmanifest",
    "/icone-180.png": "icone-180.png",
    "/icone-512.png": "icone-512.png",
    "/sw.js": "sw.js",
}
TECLAS = re.compile(r"^(Enter|Escape|Up|Down|Left|Right|Tab|BTab|Space|BSpace|C-[a-z]|[a-z0-9])$")


class Recusa(Exception):
    def __init__(self, codigo: int, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def identidade() -> tuple[str, str]:
    """Login da Tailscale do dono do PC e o nome do PC na rede."""
    js = json.loads(subprocess.run(["tailscale", "status", "--json"], capture_output=True,
                                   text=True, timeout=15, check=True).stdout)
    login = js["User"][str(js["Self"]["UserID"])]["LoginName"]
    return login, js["Self"]["DNSName"].rstrip(".")


def tmux(*args: str, entrada: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], input=entrada, capture_output=True, text=True, timeout=5)


def curto(caminho: str) -> str:
    casa = str(Path.home())
    return "~" + caminho[len(casa):] if caminho == casa or caminho.startswith(casa + "/") else caminho


# ---------------------------------------------------------------- conversa (jsonl)

NOMES_CLI = {"Edit": "Update", "MultiEdit": "Update", "Grep": "Search", "Glob": "Search",
             "WebSearch": "Web Search", "WebFetch": "Fetch", "NotebookEdit": "Update"}


def resumo_ferramenta(nome: str, ent: dict) -> tuple[str, str]:
    """(linha principal, linha de baixo) de uma chamada de ferramenta, como o CLI escreve:
    Bash mostra a descrição e embaixo "$ comando"; o resto vira Nome(argumento)."""
    if nome == "Bash":
        comando = (ent.get("command") or "").strip()
        primeira = comando.split("\n")[0] + (" …" if "\n" in comando else "")
        return (ent.get("description") or primeira)[:300], ("$ " + primeira)[:300] if ent.get("description") else ""
    rotulo = NOMES_CLI.get(nome, nome)
    if nome.startswith("mcp__"):
        partes = nome.split("__")
        servidor = partes[1].replace("plugin_", "") if len(partes) > 1 else "mcp"
        rotulo = f"{servidor} - {partes[-1]} (MCP)"
    arg = ""
    if nome in ("Read", "Edit", "MultiEdit", "Write", "NotebookEdit"):
        arg = curto(ent.get("file_path") or ent.get("notebook_path") or "")
    elif nome in ("Grep", "Glob"):
        arg = ent.get("pattern", "")
    elif nome == "WebSearch":
        arg = f'"{ent.get("query", "")}"'
    elif nome == "WebFetch":
        arg = ent.get("url", "")
    elif nome in ("Agent", "Task"):
        arg = ent.get("description", "")
    elif nome == "Skill":
        arg = ent.get("skill", "")
    elif nome == "AskUserQuestion":
        arg = ((ent.get("questions") or [{}])[0]).get("question", "")
    else:
        arg = next((v for v in ent.values() if isinstance(v, str) and v.strip()), "")
    arg = " ".join(str(arg).split())
    return (f"{rotulo}({arg[:200]})" if arg else rotulo), ""


COMANDO = re.compile(r"<command-name>(.*?)</command-name>.*?<command-args>(.*?)</command-args>", re.S)
SAIDA_COMANDO = re.compile(r"<local-command-stdout>(.*?)</local-command-stdout>", re.S)
BASH_ENTRADA = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)
BASH_SAIDA = re.compile(r"<bash-stdout>(.*?)</bash-stdout>(?:<bash-stderr>(.*?)</bash-stderr>)?", re.S)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
IMAGEM_TOKEN = re.compile(r"\[Image #\d+\]")
COLAGEM = re.compile(r"</?pasted_content[^>]*>\n?")  # o Claude envolve colagem grande nisso
LINHA_ANEXO = re.compile(r"^(?:Anexo: )?(/\S+/anexos/(\d{4}-\d{2}-\d{2}/[^\s/]+))$")
EXT_IMAGEM = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def chave_mensagem(texto: str) -> str:
    """Texto da mensagem sem as marcas de anexo, pra achar o envio que a originou."""
    linhas = [l for l in IMAGEM_TOKEN.sub(" ", texto).split("\n")
              if not LINHA_ANEXO.match(l.strip()) and l.strip() not in ("[anexo]", "Imagens:")
              and not l.strip().startswith("Imagens: /")]
    return " ".join(" ".join(linhas).split())


class Enviados:
    """Quais anexos foram em cada mensagem mandada pelo painel (arquivo anexos/enviados.jsonl)."""

    def __init__(self) -> None:
        self.trava = threading.Lock()
        self.mapa: dict[str, list[str]] = {}
        self.carregado = False

    def _carregar(self) -> None:
        if self.carregado:
            return
        self.carregado = True
        try:
            for linha in (ANEXOS / "enviados.jsonl").read_text().splitlines():
                d = json.loads(linha)
                self.mapa[d["chave"]] = d["anexos"]
        except (OSError, ValueError, KeyError):
            pass

    def guardar(self, chave: str, anexos: list[str]) -> None:
        with self.trava:
            self._carregar()
            self.mapa[chave] = anexos
            with open(ANEXOS / "enviados.jsonl", "a") as f:
                f.write(json.dumps({"chave": chave, "anexos": anexos, "quando": time.time()}, ensure_ascii=False) + "\n")

    def de(self, chave: str) -> list[str] | None:
        with self.trava:
            self._carregar()
            return self.mapa.get(chave)


ENVIADOS = Enviados()

ENTREGA = re.compile(r"\[entrega:([A-Za-z0-9_-]{6,16})\]")
CAMPOS_ENTREGA = ("id", "quando", "tipo", "nome", "tamanho", "mime", "larg", "alt", "dur", "legenda", "url")


class Entregas:
    """O registro do bin/entregar (entregas/registro.jsonl), relido só quando o arquivo muda."""

    def __init__(self) -> None:
        self.trava = threading.Lock()
        self.mtime = None
        self.por_id: dict[str, dict] = {}

    def _carregar(self) -> None:
        arq = ENTREGAS / "registro.jsonl"
        try:
            mtime = arq.stat().st_mtime_ns
        except OSError:
            self.mtime, self.por_id = None, {}
            return
        if mtime == self.mtime:
            return
        por_id = {}
        for linha in arq.read_text().splitlines():
            try:
                d = json.loads(linha)
                por_id[d["id"]] = d
            except (ValueError, KeyError, TypeError):
                continue
        self.mtime, self.por_id = mtime, por_id

    def item(self, eid: str) -> dict | None:
        with self.trava:
            self._carregar()
            return self.por_id.get(eid)

    def publico(self, eid: str) -> dict:
        """O que a página vê (sem caminho do PC); `previa` diz se tem imagem leve pra mostrar."""
        d = self.item(eid)
        if not d:
            return {"id": eid, "faltando": True}
        saida = {k: d[k] for k in CAMPOS_ENTREGA if k in d}
        saida["previa"] = bool(d.get("previa"))
        if d.get("rel") and not (ENTREGAS / d["rel"]).is_file():
            saida["faltando"] = True
        return saida

    def lista(self) -> list[dict]:
        with self.trava:
            self._carregar()
            ids = list(self.por_id)
        return [self.publico(i) for i in reversed(ids)]


ENTREGAS_REG = Entregas()


class Conversa:
    """Lê o .jsonl da sessão aos pedaços e guarda a lista de itens que a página desenha.

    A lista só cresce, então a página pede "do item N em diante". O resultado de uma
    ferramenta vira um item próprio que só marca a chamada como concluída; o texto
    completo da entrada e da saída é relido do arquivo quando a página pede.
    """

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.trava = threading.Lock()
        self._zerar()

    def _zerar(self) -> None:
        self.offset = 0
        self.itens: list[dict] = []
        self.ferramentas: dict[str, dict] = {}  # id -> {"uso": (pos, tam), "res": (pos, tam)}
        self.entregadores: set[str] = set()  # chamadas do bin/entregar: a saída vira cartão
        self.titulo_ia = ""
        self.titulo_proprio = ""
        self.primeiro_prompt = ""

    @property
    def titulo(self) -> str:
        return self.titulo_proprio or self.titulo_ia or self.primeiro_prompt[:60] or "Nova conversa"

    def atualizar(self) -> None:
        with self.trava:
            try:
                tamanho = self.caminho.stat().st_size
            except OSError:
                return
            if tamanho < self.offset:  # arquivo reescrito: recomeça
                self._zerar()
            if tamanho == self.offset:
                return
            with open(self.caminho, "rb") as f:
                f.seek(self.offset)
                dados = f.read(tamanho - self.offset)
            fim = dados.rfind(b"\n")
            if fim < 0:  # linha ainda sendo escrita
                return
            pos = self.offset
            for linha in dados[: fim + 1].splitlines(keepends=True):
                try:
                    self._linha(json.loads(linha), pos, len(linha))
                except (ValueError, KeyError, TypeError, AttributeError):
                    pass
                pos += len(linha)
            self.offset = pos

    def _novo(self, item: dict, d: dict) -> None:
        item["i"] = len(self.itens)
        if d.get("timestamp"):
            item["ts"] = d["timestamp"]
        self.itens.append(item)

    def _linha(self, d: dict, pos: int, tam: int) -> None:
        tipo = d.get("type")
        if tipo == "ai-title":
            self.titulo_ia = d.get("aiTitle") or self.titulo_ia
            return
        if tipo == "custom-title":
            self.titulo_proprio = d.get("customTitle") or self.titulo_proprio
            return
        if d.get("isSidechain"):
            return
        if tipo == "user":
            self._usuario(d, pos, tam)
        elif tipo == "assistant":
            self._assistente(d, pos, tam)
        elif tipo == "system":
            sub = d.get("subtype")
            if sub == "local_command":
                conteudo = d.get("content") or ""
                if m := COMANDO.search(conteudo):
                    nome, args = m.group(1).strip(), m.group(2).strip()
                    if not (nome == "/clear" and not self.itens):
                        self._novo({"t": "cmd", "txt": f"{nome} {args}".strip()}, d)
                m = SAIDA_COMANDO.search(conteudo)
                texto = ANSI.sub("", m.group(1)).strip() if m else ""
                if texto:
                    self._novo({"t": "saida", "txt": texto}, d)
            elif sub == "compact_boundary":
                self._novo({"t": "marco", "txt": "Conversa resumida pra caber no contexto"}, d)
            elif sub == "turn_duration" and d.get("durationMs"):
                self._novo({"t": "fim", "ms": d["durationMs"]}, d)
        elif tipo == "attachment":
            anexo = d.get("attachment") or {}
            if anexo.get("type") == "queued_command" and anexo.get("commandMode") == "prompt":
                texto = anexo.get("prompt")
                if isinstance(texto, str) and texto.strip():
                    self._novo({"t": "u", "txt": texto, "fila": True}, d)

    def _usuario(self, d: dict, pos: int, tam: int) -> None:
        conteudo = d["message"]["content"]
        if d.get("isCompactSummary"):
            self._novo({"t": "marco", "txt": "Conversa resumida pra caber no contexto"}, d)
            return
        if isinstance(conteudo, str) and (m := SAIDA_COMANDO.search(conteudo)):
            texto = ANSI.sub("", m.group(1)).strip()
            if texto:
                self._novo({"t": "saida", "txt": texto}, d)
            return
        if d.get("isMeta"):
            return
        if isinstance(conteudo, str):
            self._texto_usuario(conteudo, d)
            return
        textos, imagens = [], 0
        for bloco in conteudo:
            t = bloco.get("type")
            if t == "tool_result":
                ref = self.ferramentas.setdefault(bloco.get("tool_use_id", ""), {})
                ref["res"] = (pos, tam)
                self._novo({"t": "r", "id": bloco.get("tool_use_id"), "erro": bool(bloco.get("is_error"))}, d)
                if bloco.get("tool_use_id") in self.entregadores:
                    c = bloco.get("content")
                    texto = c if isinstance(c, str) else "\n".join(
                        x.get("text", "") for x in c or [] if isinstance(x, dict) and x.get("type") == "text")
                    ids = list(dict.fromkeys(ENTREGA.findall(texto)))
                    if ids:
                        self._novo({"t": "entrega", "itens": [ENTREGAS_REG.publico(i) for i in ids]}, d)
            elif t == "text":
                textos.append(bloco.get("text", ""))
            elif t == "image":
                imagens += 1
        if textos or imagens:
            self._texto_usuario("\n".join(textos), d, imagens)

    def _texto_usuario(self, texto: str, d: dict, imagens: int = 0) -> None:
        bruto = COLAGEM.sub("", texto).strip()
        if bruto.startswith("[Request interrupted"):
            self._novo({"t": "marco", "txt": "Interrompido"}, d)
            return
        if bruto.startswith(("<task-notification>", "<local-command-caveat>", "<system-reminder>",
                             "[Image: source:", "[Image: original")):
            return
        if m := COMANDO.search(bruto):
            nome, args = m.group(1).strip(), m.group(2).strip()
            if nome == "/clear" and not self.itens:  # toda conversa nova começa com ele
                return
            self._novo({"t": "cmd", "txt": f"{nome} {args}".strip()}, d)
            return
        if m := BASH_ENTRADA.search(bruto):
            self._novo({"t": "u", "txt": "!" + m.group(1)}, d)
            return
        if m := BASH_SAIDA.search(bruto):
            saida = "\n".join(p for p in (m.group(1), m.group(2) or "") if p.strip())
            self._novo({"t": "saida", "txt": ANSI.sub("", saida).strip() or "(sem saída)"}, d)
            return
        if not bruto and not imagens:
            return
        chave = chave_mensagem(bruto)
        if not self.primeiro_prompt:
            self.primeiro_prompt = chave
        item = {"t": "u", "txt": bruto}
        anexos = ENVIADOS.de(chave)
        if anexos:
            item["anx"] = anexos
        if imagens:
            item["img"] = imagens
        self._novo(item, d)

    def _assistente(self, d: dict, pos: int, tam: int) -> None:
        conteudo = d["message"].get("content") or []
        if isinstance(conteudo, str):
            conteudo = [{"type": "text", "text": conteudo}]
        erro = d.get("isApiErrorMessage")
        for bloco in conteudo:
            t = bloco.get("type")
            if t == "text":
                texto = bloco.get("text", "").strip()
                if texto and texto != "No response requested.":
                    self._novo({"t": "erro" if erro else "a", "txt": texto}, d)
            elif t == "tool_use":
                fid = bloco.get("id", "")
                self.ferramentas.setdefault(fid, {})["uso"] = (pos, tam)
                if bloco.get("name") == "Bash" and "bin/entregar" in str((bloco.get("input") or {}).get("command", "")):
                    self.entregadores.add(fid)
                linha, sub = resumo_ferramenta(bloco.get("name", "?"), bloco.get("input") or {})
                item = {"t": "f", "id": fid, "txt": linha}
                if sub:
                    item["sub"] = sub
                self._novo(item, d)

    def _ler(self, pos_tam: tuple[int, int] | None) -> dict | None:
        if not pos_tam:
            return None
        with open(self.caminho, "rb") as f:
            f.seek(pos_tam[0])
            return json.loads(f.read(pos_tam[1]))

    def detalhe(self, fid: str) -> dict:
        """Entrada e saída completas de uma ferramenta, sem cortar nada."""
        ref = self.ferramentas.get(fid)
        if not ref:
            raise Recusa(404, "Essa ação não está nesta conversa.")
        uso, res = self._ler(ref.get("uso")), self._ler(ref.get("res"))
        nome, entrada = "?", {}
        for b in (uso or {}).get("message", {}).get("content", []):
            if b.get("type") == "tool_use" and b.get("id") == fid:
                nome, entrada = b.get("name", "?"), b.get("input") or {}
        saida, imagens, erro = "", [], False
        for b in (res or {}).get("message", {}).get("content", []) if res else []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") == fid:
                erro = bool(b.get("is_error"))
                c = b.get("content")
                if isinstance(c, str):
                    saida = c
                else:
                    partes = []
                    for x in c or []:
                        if x.get("type") == "text":
                            partes.append(x.get("text", ""))
                        elif x.get("type") == "image" and (src := x.get("source") or {}).get("type") == "base64":
                            imagens.append(f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}")
                    saida = "\n".join(partes)
        return {"nome": nome, "entrada": formatar_entrada(nome, entrada), "saida": ANSI.sub("", saida),
                "imagens": imagens, "erro": erro, "pronto": res is not None}


def formatar_entrada(nome: str, ent: dict) -> list[dict]:
    """Blocos {rotulo, txt} pra mostrar a entrada de um jeito legível."""
    if nome == "Bash":  # a descrição já aparece na linha da ação
        return [{"rotulo": "Comando", "txt": ent.get("command", ""), "mono": True}]
    if nome == "Edit":
        return [{"rotulo": "Arquivo", "txt": curto(ent.get("file_path", ""))},
                {"rotulo": "Trocou", "txt": ent.get("old_string", ""), "mono": True, "tom": "sai"},
                {"rotulo": "Por", "txt": ent.get("new_string", ""), "mono": True, "tom": "entra"}]
    if nome == "Write":
        return [{"rotulo": "Arquivo", "txt": curto(ent.get("file_path", ""))},
                {"rotulo": "Conteúdo", "txt": ent.get("content", ""), "mono": True, "tom": "entra"}]
    if nome in ("Agent", "Task"):
        return [{"rotulo": "Tarefa", "txt": ent.get("description", "")},
                {"rotulo": "Instruções", "txt": ent.get("prompt", "")}]
    return [{"rotulo": "Entrada", "txt": json.dumps(ent, ensure_ascii=False, indent=2), "mono": True}]


_conversas: dict[Path, Conversa] = {}
_conversas_trava = threading.Lock()


def conversa_de(caminho: Path | None) -> Conversa | None:
    if not caminho:
        return None
    with _conversas_trava:
        conv = _conversas.get(caminho)
        if conv is None:
            conv = _conversas[caminho] = Conversa(caminho)
    conv.atualizar()
    return conv


# ---------------------------------------------------------------- tela do tmux

OPCAO = re.compile(r"^(?:[❯›>↓↑]\s*)?(\d{1,2})[.)]\s+(.+?)$")
MARCADOR = ("❯", "›")
MAIS = re.compile(r"^…\s*\+(\d+)\s")
DUAS_COLUNAS = re.compile(r"^(.*?\S)\s{2,}(\S.*)$")
DICAS_PERGUNTA = ("esc to cancel", "enter to select", "enter to confirm", "esc to go back", "to navigate",
                  "enter to continue", "esc to clear", "esc to close", "esc to exit")
BORDAS = "│┃╭╮╰╯"
SEPARADOR = re.compile(r"^\s*[─━═▔▁]{8,}")
TRACEJADO = re.compile(r"^\s*[╌┄┈╍-]{8,}\s*$")
DICA = re.compile(r"^(?P<teclas>\S+(?: keys)?)\s+(?P<verbo>to|for)\s+(?P<acao>.+)$")
TECLA_DICA = r"(?:[←→↑↓]|Tab|Enter|Space|Esc)"
DICA_NA_LINHA = re.compile(rf"(?P<teclas>{TECLA_DICA}(?:/{TECLA_DICA})*)\s+to\s+(?P<acao>\w+)\s*$")
NOMES_TECLA = {"enter": "Enter", "return": "Enter", "esc": "Escape", "escape": "Escape", "tab": "Tab",
               "space": "Space", "shift+tab": "BTab", "←": "Left", "→": "Right", "↑": "Up", "↓": "Down"}
SETAS = [{"tecla": "Up", "nome": "↑"}, {"tecla": "Down", "nome": "↓"}]


def _sem_borda(linha: str) -> str:
    linha = linha.rstrip()
    if linha.lstrip().startswith(tuple(BORDAS)):
        linha = linha.replace(linha.lstrip()[0], " ", 1)
    return linha.rstrip(" " + BORDAS)


def _coluna(linha: str) -> int:
    return len(linha) - len(linha.lstrip())


def teclas_de(texto: str) -> list[dict]:
    """"Enter/↓", "Tab/Arrow keys", "s", "Ctrl+A" -> teclas do tmux. Lista vazia = não é dica."""
    if texto.lower() == "type":
        return [{"tecla": "digitar", "nome": "Digitar"}]
    saida = []
    for parte in texto.split("/"):
        p = parte.strip()
        baixo = p.lower()
        if baixo in NOMES_TECLA:
            saida.append({"tecla": NOMES_TECLA[baixo], "nome": p})
        elif baixo in ("arrow keys", "arrows"):
            saida += SETAS
        elif m := re.fullmatch(r"ctrl\+([a-z])", baixo):
            saida.append({"tecla": f"C-{m.group(1)}", "nome": p})
        elif re.fullmatch(r"[a-z0-9]", baixo):
            saida.append({"tecla": baixo, "nome": p})
        else:
            return []
    return saida


def dicas_do_rodape(linhas: list[str]) -> list[dict]:
    """"Enter to confirm · s for this session only · Esc to cancel" -> uma dica por trecho."""
    saida = []
    for parte in " ".join(l.strip() for l in linhas).split("·"):
        m = DICA.match(parte.strip())
        if m and (teclas := teclas_de(m.group("teclas"))):
            saida.append({"teclas": teclas, "acao": f"{m.group('verbo')} {m.group('acao')}", "legenda": ""})
    return saida


def dicas_no_corpo(linhas: list[str]) -> list[dict]:
    """Dicas soltas dentro do menu ("◐ Medium effort ←/→ to adjust", "Ultracode off / Tab to toggle")."""
    saida = []
    for n, linha in enumerate(linhas):
        m = DICA_NA_LINHA.search(linha)
        if not m or not (teclas := teclas_de(m.group("teclas"))):
            continue
        antes = linha[:m.start()]
        if antes.strip() and not antes.endswith("   "):
            legenda = antes.strip()  # mesma frase: "◐ Medium effort (default)"
        else:  # dica sozinha: a legenda é o que está na mesma coluna, na linha de cima
            cima = next((linhas[x] for x in range(n - 1, -1, -1) if linhas[x].strip()), "")
            legenda = re.split(r"\s{3,}", cima[m.start():].strip())[0] if len(cima) > m.start() else ""
        saida.append({"teclas": teclas, "acao": f"to {m.group('acao')}", "legenda": legenda})
    return saida


def achar_pergunta(linhas: list[str], colunas: int = 80, exigir_dica: bool = False) -> dict | None:
    """Menu do Claude aberto no fim da tela, lido como o CLI mostra.

    Só vale se a dica de teclas ("Esc to cancel"...) estiver nas últimas linhas: no meio da
    conversa o mesmo texto pode aparecer citado sem ser um menu. Três formas:
    - "lista": opções com número ("1. Yes") ou com cursor (❯), como permissão e /model;
    - "regua": níveis numa linha com ▲ embaixo do atual, como /effort;
    - "livre": qualquer outro menu (/config, /rewind), mostrado tal como está na tela.
    Os botões de tecla saem das dicas do próprio menu, com o mesmo texto do CLI.
    `exigir_dica`: só aceita menu com rodapé de teclas (fora da tela cheia do Claude, o ❯ do
    prompt do shell parece o cursor de um menu sem rodapé).
    """
    janela = [_sem_borda(l) for l in linhas[-45:]]
    deslocamento = len(linhas) - len(janela)
    cheias = [n for n, l in enumerate(janela) if l.strip()]
    if not cheias:
        return None
    com_dica = any(d in janela[n].lower() for n in cheias[-4:] for d in DICAS_PERGUNTA)
    caixa = any(janela[n].startswith("❯") and n - 1 >= 0 and LINHA_CAIXA.match(janela[n - 1].strip() or "x")
                for n in cheias[-6:])
    cursor_no_fim = any(janela[n].strip().startswith(MARCADOR) for n in cheias[-8:])
    if not com_dica and (exigir_dica or caixa or not cursor_no_fim):
        return None
    # rodapé: a última linha e as de cima que continuam a mesma lista de dicas (separadas por ·)
    fim = cheias[-1]
    ini_rodape = fim
    while ini_rodape - 1 >= 0 and "·" in janela[ini_rodape - 1] and janela[ini_rodape - 1].strip():
        ini_rodape -= 1
    dicas = dicas_do_rodape(janela[ini_rodape:fim + 1])
    if not dicas:  # a última linha não é de dicas (menu sem rodapé): ela faz parte do menu
        ini_rodape = fim + 1
    corpo = janela[:ini_rodape]

    regua = achar_regua(corpo)
    opcoes, linhas_op, numerado = [], [], False
    if not regua:
        # Rewind (Esc duas vezes): cada opção é um bloco separado por linha em branco
        sep = max((n for n, l in enumerate(corpo) if SEPARADOR.match(l)), default=-1)
        em_blocos = any(l.strip() == "Rewind" for l in corpo[sep + 1:])
        opcoes, linhas_op, numerado = achar_opcoes(corpo, colunas, em_blocos)
    # topo do menu: a linha separadora acima da primeira opção (ou da régua, ou do rodapé)
    ancora = linhas_op[0] if linhas_op else regua["linha_barra"] if regua else ini_rodape
    topo = max(0, ancora - 30)
    for n in range(ancora - 1, -1, -1):
        if SEPARADOR.match(corpo[n]):
            topo = n + 1
            break
    regiao = corpo[topo:]
    dicas = dicas_no_corpo(regiao) + dicas
    base = {"dicas": dicas, "ini": deslocamento + topo, "fim": deslocamento + ini_rodape}  # sem o rodapé

    if regua:
        textos = [l.strip() for l in corpo[topo:regua["linha_barra"]] if l.strip()]
        titulo = textos[0] if textos else ""
        extremos = textos[-1].split() if len(textos) > 1 else []
        return {**base, "tipo": "regua", "blocos": [{"t": "titulo", "txt": titulo}] if titulo else [],
                "pergunta": titulo, "niveis": regua["niveis"], "atual": regua["atual"],
                "extremos": extremos if len(extremos) == 2 else [], "opcoes": [],
                "assinatura": hashlib.sha1(json.dumps([titulo, regua["niveis"]]).encode()).hexdigest()[:10]}
    if opcoes:
        blocos = blocos_da_pergunta(corpo[topo:linhas_op[0]], colunas)
        ultima = linhas_op[-1]
        notas = [l.strip() for l in corpo[ultima + 1:] if l.strip() and not SEPARADOR.match(l)
                 and _coluna(l) <= _coluna(corpo[ultima]) + 1 and not DICA_NA_LINHA.search(l)]
        texto = "\n\n".join(b["txt"] for b in blocos)
        so_setas = any({t["tecla"] for t in d["teclas"]} == {"Up", "Down"} for d in dicas)
        if (numerado or any(o["sel"] for o in opcoes)) and not so_setas:
            dicas.insert(0, {"teclas": SETAS, "acao": "" if not com_dica else "to navigate", "legenda": ""})
        if not com_dica:
            dicas.append({"teclas": [{"tecla": "Enter", "nome": "Enter"}, {"tecla": "Escape", "nome": "Esc"}],
                          "acao": "", "legenda": ""})
        return {**base, "dicas": dicas, "tipo": "lista", "blocos": blocos, "pergunta": texto,
                "opcoes": opcoes, "numerado": numerado, "notas": notas,
                "assinatura": hashlib.sha1(json.dumps([texto, numerado]).encode()).hexdigest()[:10]}
    titulo = next((l.strip() for l in regiao if l.strip()), "")
    if not any(t["tecla"] in ("Up", "Down") for d in dicas for t in d["teclas"]):
        base["dicas"] = [{"teclas": SETAS, "acao": "to navigate", "legenda": ""}] + dicas
    return {**base, "tipo": "livre", "pergunta": titulo, "blocos": [], "opcoes": [],
            "texto": "\n".join(regiao),
            "assinatura": hashlib.sha1(titulo.encode()).hexdigest()[:10]}


URL_TELA = re.compile(r"https?://[^\s<>\"']+")
URL_PEDACO = re.compile(r"[^\s<>\"']+")


def links_da_tela(linhas: list[str], largura: int) -> list[str]:
    """Links inteiros da tela do terminal. O CLI quebra link comprido na borda (o do /login ocupa
    6 linhas): se o link chega na última coluna, a linha de baixo, colada na margem, é a continuação."""
    saida: list[str] = []
    n = 0
    while n < len(linhas):
        for m in URL_TELA.finditer(linhas[n]):
            url, na_borda, k = m.group(0), m.end() >= largura, n
            while na_borda and k + 1 < len(linhas) and (pedaco := URL_PEDACO.match(linhas[k + 1])):
                url += pedaco.group(0)
                na_borda = pedaco.end() >= largura
                k += 1
            url = url.rstrip(".,;:)]}'\"")
            if url not in saida:
                saida.append(url)
        n += 1
    return saida


def achar_opcoes(acima: list[str], colunas: int, em_blocos: bool = False) -> tuple[list[dict], list[int], bool]:
    """Opções numeradas (a última sequência 1, 2, 3...) ou, sem número, a linha com ❯ e as
    vizinhas que começam na mesma coluna. Descrição em segunda coluna ou na linha de baixo."""
    opcoes, linhas_op = [], []
    for n, linha in enumerate(acima):
        m = OPCAO.match(linha.strip())
        if not m:
            continue
        numero = int(m.group(1))
        if numero == 1:
            opcoes, linhas_op = [], []
        if numero == len(opcoes) + 1:
            texto = m.group(2).strip()
            op = {"n": numero, "txt": texto, "sel": linha.strip().startswith(MARCADOR)}
            if mc := DUAS_COLUNAS.match(texto):
                op["txt"], op["desc"] = mc.group(1), mc.group(2)
                op["col_desc"] = linha.rfind(mc.group(2))
            opcoes.append(op)
            linhas_op.append(n)
    if len(opcoes) >= 2:
        for k, n in enumerate(linhas_op):
            limite = linhas_op[k + 1] if k + 1 < len(linhas_op) else len(acima)
            col = _coluna(acima[n]) + 3
            anterior = acima[n]
            col_desc = opcoes[k].pop("col_desc", None)
            for x in range(n + 1, limite):
                l = acima[x]
                if not l.strip() or _coluna(l) < col or MAIS.match(l.strip()) or SEPARADOR.match(l):
                    break
                if col_desc is not None and _coluna(l) >= col_desc - 1:
                    chave = "desc"
                else:
                    chave = "txt" if quebrou(anterior, colunas) and "desc" not in opcoes[k] else "desc"
                opcoes[k][chave] = (opcoes[k].get(chave, "") + " " + l.strip()).strip()
                anterior = l
        return opcoes, linhas_op, True
    sel = next((n for n in range(len(acima) - 1, -1, -1) if acima[n].strip().startswith(MARCADOR)), None)
    if sel is None:
        return [], [], False
    if em_blocos:
        return opcoes_em_blocos(acima, sel)
    coluna = _coluna(acima[sel]) + 2
    topo = sel
    while topo - 1 >= 0 and acima[topo - 1].strip() and _coluna(acima[topo - 1]) == coluna:
        topo -= 1
    base = sel
    while base + 1 < len(acima) and acima[base + 1].strip() and _coluna(acima[base + 1]) >= coluna:
        base += 1
    opcoes, linhas_op = [], []
    for n in range(topo, base + 1):
        texto = acima[n].strip()
        if n != sel and _coluna(acima[n]) > coluna and opcoes:
            opcoes[-1]["desc"] = (opcoes[-1].get("desc", "") + " " + texto).strip()
            continue
        op = {"n": len(opcoes) + 1, "txt": texto.lstrip("❯› ").strip(), "sel": n == sel}
        if mc := DUAS_COLUNAS.match(op["txt"]):  # "Auto-compact            true"
            op["txt"], op["desc"] = mc.group(1), mc.group(2)
        opcoes.append(op)
        linhas_op.append(n)
    if len(opcoes) < 2:
        return [], [], False
    return opcoes, linhas_op, False


def opcoes_em_blocos(acima: list[str], sel: int) -> tuple[list[dict], list[int], bool]:
    """Opções separadas por linha em branco, cada uma com a descrição embaixo, como o Rewind
    (Esc duas vezes): "diga só: um / No code changes", ..., "❯ (current)"."""
    coluna = _coluna(acima[sel]) + 2
    def dentro(n: int) -> bool:
        return not acima[n].strip() or _coluna(acima[n]) >= coluna
    topo, base = sel, sel
    while topo - 1 >= 0 and dentro(topo - 1):
        topo -= 1
    while base + 1 < len(acima) and dentro(base + 1):
        base += 1
    blocos, atual = [], []
    for n in range(topo, base + 1):
        if acima[n].strip():
            atual.append(n)
        elif atual:
            blocos.append(atual)
            atual = []
    if atual:
        blocos.append(atual)
    opcoes, linhas_op = [], []
    for b in blocos:
        if b[0] != sel and _coluna(acima[b[0]]) != coluna:
            continue
        op = {"n": len(opcoes) + 1, "txt": acima[b[0]].strip().lstrip("❯› ").strip(), "sel": b[0] == sel}
        if len(b) > 1:
            op["desc"] = " · ".join(acima[x].strip() for x in b[1:])
        opcoes.append(op)
        linhas_op.append(b[0])
    if len(opcoes) < 2 or not any(o["sel"] for o in opcoes):
        return [], [], False
    return opcoes, linhas_op, False


def achar_regua(acima: list[str]) -> dict | None:
    """Régua (ex.: /effort): níveis numa linha e ▲ embaixo do atual. Só os rótulos que ficam
    debaixo da barra contam; com o terminal largo o Claude põe outras coisas ao lado."""
    barra = next((n for n in range(len(acima) - 1, -1, -1) if "▲" in acima[n] and acima[n].count("─") >= 8), None)
    if barra is None:
        return None
    marca = acima[barra].index("▲")
    trecho = next((m for m in re.finditer(r"[─▲]+", acima[barra]) if m.start() <= marca < m.end()), None)
    linha_rotulos = next((acima[n] for n in range(barra + 1, len(acima)) if acima[n].strip()), "")
    rotulos = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", linha_rotulos)
               if trecho.start() - 3 <= m.start() and m.end() <= trecho.end() + 3]
    if len(rotulos) < 2:
        return None
    atual = min(range(len(rotulos)), key=lambda k: abs((rotulos[k][0] + rotulos[k][1]) / 2 - marca))
    return {"linha_barra": barra, "niveis": [r[2] for r in rotulos], "atual": atual}


def quebrou(linha: str, colunas: int) -> bool:
    """A linha chegou perto da borda: o terminal quebrou o texto, não é parágrafo novo."""
    return len(linha.rstrip()) >= colunas - 12


def blocos_da_pergunta(linhas: list[str], colunas: int) -> list[dict]:
    blocos: list[dict] = []
    atual: list[str] = []
    codigo: list[str] | None = None

    def fechar() -> None:
        if atual:
            texto = " ".join(atual)
            if not texto.startswith("Tip:"):  # dica do próprio Claude Code, só polui
                blocos.append({"t": "titulo" if not blocos else "p", "txt": texto})
            atual.clear()

    for n, linha in enumerate(linhas):
        if TRACEJADO.match(linha):
            if codigo is None:
                fechar()
                codigo = []
            else:
                blocos.append({"t": "cod", "txt": "\n".join(codigo).strip("\n")})
                codigo = None
            continue
        if codigo is not None:
            codigo.append(linha[1:] if linha.startswith(" ") else linha)
            continue
        if not linha.strip():
            fechar()
            continue
        atual.append(linha.strip())
        if not quebrou(linha, colunas):
            fechar()
    if codigo:
        blocos.append({"t": "cod", "txt": "\n".join(codigo).strip("\n")})
    fechar()
    return blocos


PALETA = ["#3b3934", "#f2727f", "#74c27f", "#e6b450", "#8fa8f0", "#c99cf0", "#6cc4c4", "#ecebe4",
          "#85817a", "#f5a0a8", "#9ad6a2", "#f0cd85", "#b3c4f7", "#dcbdf7", "#9ad9d9", "#faf9f5"]
SGR = re.compile(r"\x1b\[([0-9;:]*)m")
OUTRO_ESC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Z0-9]|\x1b[=>]")  # OSC 8 = link do CLI
SGR_LIGA = {1: "b", 2: "d", 3: "i", 4: "u", 7: "r"}
SGR_DESLIGA = {23: "i", 24: "u", 27: "r"}


def _cor256(n: int) -> str:
    if n < 16:
        return PALETA[n]
    if n < 232:
        n -= 16
        niveis = [0, 95, 135, 175, 215, 255]
        return "#%02x%02x%02x" % (niveis[n // 36], niveis[(n // 6) % 6], niveis[n % 6])
    cinza = 8 + 10 * (n - 232)
    return "#%02x%02x%02x" % (cinza, cinza, cinza)


def _estilo_limpo() -> dict:
    return {"fg": None, "bg": None, "b": False, "d": False, "i": False, "u": False, "r": False}


def ansi_html(linha: str) -> str:
    """Uma linha do capture-pane -e em HTML seguro: texto escapado + spans só com estilo."""
    est = _estilo_limpo()
    saida = []
    for k, parte in enumerate(SGR.split(linha)):
        if k % 2 == 1:  # parâmetros de cor/estilo
            nums = [int(x) if x.isdigit() else 0 for x in re.split(r"[;:]", parte or "0")]
            j = 0
            while j < len(nums):
                c = nums[j]
                if c == 0:
                    est = _estilo_limpo()
                elif c in SGR_LIGA:
                    est[SGR_LIGA[c]] = True
                elif c == 22:
                    est["b"] = est["d"] = False
                elif c in SGR_DESLIGA:
                    est[SGR_DESLIGA[c]] = False
                elif 30 <= c <= 37 or 90 <= c <= 97:
                    est["fg"] = PALETA[c - 30 if c < 90 else c - 82]
                elif 40 <= c <= 47 or 100 <= c <= 107:
                    est["bg"] = PALETA[c - 40 if c < 100 else c - 92]
                elif c in (39, 49):
                    est["fg" if c == 39 else "bg"] = None
                elif c in (38, 48) and j + 1 < len(nums):
                    alvo = "fg" if c == 38 else "bg"
                    if nums[j + 1] == 5 and j + 2 < len(nums):
                        est[alvo] = _cor256(nums[j + 2])
                        j += 2
                    elif nums[j + 1] == 2 and j + 4 < len(nums):
                        est[alvo] = "#%02x%02x%02x" % tuple(min(255, v) for v in nums[j + 2:j + 5])
                        j += 4
                j += 1
            continue
        texto = OUTRO_ESC.sub("", parte)
        if not texto:
            continue
        fg, bg = est["fg"], est["bg"]
        if est["r"]:
            fg, bg = bg or "#141413", fg or "#ecebe4"
        estilo = ";".join(x for x in (
            f"color:{fg}" if fg else "", f"background:{bg}" if bg else "",
            "font-weight:700" if est["b"] else "", "opacity:.6" if est["d"] else "",
            "font-style:italic" if est["i"] else "", "text-decoration:underline" if est["u"] else "") if x)
        texto = html_lib.escape(texto)
        saida.append(f'<span style="{estilo}">{texto}</span>' if estilo else texto)
    return "".join(saida)


def tela_colorida(pane: str, ini: int = 0, fim: int | None = None) -> list[str]:
    """A tela do tmux com as cores do terminal, em HTML (pra mostrar igual ao CLI)."""
    cap = tmux("capture-pane", "-p", "-e", "-t", pane)
    linhas = cap.stdout.split("\n") if cap.returncode == 0 else []
    while linhas and not SGR.sub("", linhas[-1]).strip():
        linhas.pop()
    return [ansi_html(l) for l in linhas[ini:fim]]


def processo_claude(pane_pid: int) -> int | None:
    try:
        filhos = Path(f"/proc/{pane_pid}/task/{pane_pid}/children").read_text().split()
    except OSError:
        filhos = subprocess.run(["pgrep", "-P", str(pane_pid)], capture_output=True, text=True).stdout.split()
    for pid in filhos:
        try:
            if Path(f"/proc/{pid}/comm").read_text().strip() == "claude":
                return int(pid)
        except OSError:
            continue
    return None


def suspenso(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] in ("T", "t")
    except (OSError, IndexError):
        return True


def arquivo_da_sessao(pid: int) -> tuple[str | None, Path | None, str, str]:
    """(id da sessão, .jsonl, pasta, status) do Claude que roda no processo `pid`."""
    try:
        info = json.loads((CLAUDE / "sessions" / f"{pid}.json").read_text())
    except (OSError, ValueError):
        info = {}
    sid, status = info.get("sessionId"), info.get("status") or ""
    try:
        pasta = info.get("cwd") or os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        pasta = ""
    caminho = None
    if sid:
        achados = list((CLAUDE / "projects").glob(f"*/{sid}.jsonl"))
        caminho = achados[0] if achados else None
    elif pasta:  # sem o registro da sessão: o .jsonl mais recente da pasta do projeto
        projeto = CLAUDE / "projects" / re.sub(r"[^A-Za-z0-9]", "-", pasta)
        candidatos = sorted(projeto.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if candidatos:
            caminho, sid = candidatos[-1], candidatos[-1].stem
    return sid, caminho, pasta, status


_tela = {"quando": 0.0, "valor": None}
_tela_trava = threading.Lock()


def estado(fresco: bool = False) -> dict:
    """Retrato da sessão do tmux: Claude aberto? trabalhando? menu na tela? qual conversa?"""
    with _tela_trava:
        if not fresco and _tela["valor"] and time.monotonic() - _tela["quando"] < 0.4:
            return _tela["valor"]
        e = _estado_agora()
        _tela.update(quando=time.monotonic(), valor=e)
        return e


_config = {"mtime": None, "cheia": False}


def tela_cheia() -> bool:
    """O Claude roda com "tui": "fullscreen" (settings.json)? Relido só quando o arquivo muda."""
    arq = CLAUDE / "settings.json"
    try:
        mtime = arq.stat().st_mtime_ns
        if mtime != _config["mtime"]:
            _config.update(mtime=mtime, cheia=json.loads(arq.read_text()).get("tui") == "fullscreen")
    except (OSError, ValueError):
        _config.update(mtime=None, cheia=False)
    return _config["cheia"]


def _estado_agora() -> dict:
    r = tmux("display-message", "-p", "-t", f"{ALVO}:",
             "#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_width}\t#{pane_height}\t#{alternate_on}")
    if r.returncode != 0 or not r.stdout.strip():
        return {"tmux": False, "aberto": False, "shell": False, "pane": None, "sessao": None,
                "caminho": None, "pasta": "", "trabalhando": False, "iniciando": False, "pergunta": None, "colunas": 80,
                "tela": "", "marca": "sem-tmux"}
    pane, pane_pid, comando, largura, _altura, alt = r.stdout.strip().split("\t")
    pid = processo_claude(int(pane_pid))
    # O comando em primeiro plano do tmux não é confiável (na tela de "confiar na pasta" ele
    # diz zsh). Vale o processo: Claude filho do painel e não suspenso (Ctrl+Z devolve o
    # teclado pro shell, e aí um prompt enviado viraria comando de shell).
    aberto = pid is not None and not suspenso(pid)
    sid, caminho, pasta, status = arquivo_da_sessao(pid) if pid else (None, None, "", "")
    # Fechado: o terminal está no shell (dá pra abrir o Claude) ou com outro programa na frente?
    shell = pid is None and comando in SHELLS
    if pid is None:
        try:
            pasta = os.readlink(f"/proc/{pane_pid}/cwd")
        except OSError:
            pasta = ""
    cap = tmux("capture-pane", "-p", "-t", pane)
    linhas = [l.rstrip() for l in cap.stdout.split("\n")] if cap.returncode == 0 else []
    while linhas and not linhas[-1]:
        linhas.pop()
    tela = "\n".join(linhas)
    rodape = "\n".join(l for l in linhas[-8:]).lower()
    # Com "tui": "fullscreen" o Claude desenha tudo na tela alternativa do terminal. Processo vivo
    # com a tela normal à mostra = ainda abrindo (conversa grande demora) ou saindo: o que aparece
    # é o shell, e só vale menu com rodapé de teclas (a pergunta de confiar na pasta vem antes da
    # tela cheia).
    fora_da_tela_cheia = aberto and alt != "1" and tela_cheia()
    pergunta = achar_pergunta(linhas, int(largura), exigir_dica=fora_da_tela_cheia) if aberto else None
    if pergunta and "paste code here" in tela.lower():
        # /login: o link quebrado em várias linhas vira um botão e o código entra por um campo
        url = next((u for u in links_da_tela(linhas, int(largura)) if "oauth" in u), "")
        if url:
            pergunta = {"tipo": "login", "url": url, "pergunta": "Login", "blocos": [], "opcoes": [], "dicas": [],
                        "ini": pergunta["ini"], "fim": pergunta["fim"],
                        "assinatura": hashlib.sha1(url.encode()).hexdigest()[:10]}
    if pergunta and pergunta["tipo"] == "livre":
        pergunta["html"] = tela_colorida(pane, pergunta["ini"], pergunta["fim"])
    iniciando = fora_da_tela_cheia and not pergunta
    trabalhando = aberto and not pergunta and not iniciando and (status == "busy" or "esc to interrupt" in rodape)
    marca = hashlib.sha1(json.dumps([aberto, shell, sid, trabalhando, iniciando, pergunta], ensure_ascii=False).encode()).hexdigest()[:12]
    return {"tmux": True, "aberto": aberto, "shell": shell, "pane": pane, "pid": pid, "sessao": sid, "caminho": caminho,
            "pasta": curto(pasta), "trabalhando": trabalhando, "iniciando": iniciando, "pergunta": pergunta,
            "colunas": int(largura), "tela": tela, "marca": marca,
            "marca_tela": hashlib.sha1(tela.encode()).hexdigest()[:12]}


# ---------------------------------------------------------------- notificação (Web Push)
# O iPhone recebe notificação do painel instalado na Tela de Início, sem app. Quem cifra e
# assina é o bin/webpush.py (Python da .venv, pacote cryptography); aqui só guarda as
# inscrições e decide quando avisar: fim de turno e pergunta nova, com ninguém olhando.

CONFIG = Path(os.environ.get("PAINEL_CONFIG", RAIZ / "config"))
INSCRICOES = CONFIG / "push-inscricoes.json"
PREFS_PUSH = CONFIG / "push-prefs.json"  # quais avisos mandar (aba Configurações do painel)
WEBPUSH = [str(RAIZ / ".venv" / "bin" / "python"), "-I", str(RAIZ / "bin" / "webpush.py")]  # precisa de cryptography
SERVICOS_PUSH = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com")
_push = {"olhar": 0.0, "chave": ""}
_push_trava = threading.Lock()


def inscricoes_push() -> list[dict]:
    try:
        return json.loads(INSCRICOES.read_text())
    except (OSError, ValueError):
        return []


def guardar_inscricao(insc: dict) -> None:
    endpoint = str(insc.get("endpoint") or "")
    chaves = insc.get("keys") or {}
    host = urlparse(endpoint).hostname or ""
    if not endpoint.startswith("https://") or not host.endswith(SERVICOS_PUSH) \
            or not chaves.get("p256dh") or not chaves.get("auth"):
        raise Recusa(400, "Inscrição de notificação inválida.")
    with _push_trava:
        lista = [i for i in inscricoes_push() if i.get("endpoint") != endpoint]
        lista.append({"endpoint": endpoint, "keys": {"p256dh": str(chaves["p256dh"]), "auth": str(chaves["auth"])},
                      "desde": int(time.time())})
        CONFIG.mkdir(parents=True, exist_ok=True)
        INSCRICOES.touch(mode=0o600)
        INSCRICOES.write_text(json.dumps(lista))


def tirar_inscricao(endpoint: str) -> None:
    with _push_trava:
        lista = inscricoes_push()
        INSCRICOES.write_text(json.dumps([i for i in lista if i.get("endpoint") != endpoint]))


def prefs_push() -> dict:
    prefs = {"fim": True, "pergunta": True}
    try:
        prefs.update({k: bool(v) for k, v in json.loads(PREFS_PUSH.read_text()).items() if k in prefs})
    except (OSError, ValueError, AttributeError):
        pass
    return prefs


def guardar_prefs(corpo: dict) -> dict:
    prefs = prefs_push()
    prefs.update({k: bool(corpo[k]) for k in prefs if k in corpo})
    CONFIG.mkdir(parents=True, exist_ok=True)
    PREFS_PUSH.write_text(json.dumps(prefs))
    return prefs


def chave_push() -> str:
    if not _push["chave"]:
        r = subprocess.run(WEBPUSH + ["--chave"], capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or not r.stdout.strip():
            raise Recusa(500, "Não consegui gerar a chave das notificações.")
        _push["chave"] = r.stdout.strip()
    return _push["chave"]


def notificar(titulo: str, texto: str, tag: str) -> None:
    """Manda sem segurar quem chamou; o resultado vai pro log."""
    def rodar() -> None:
        r = subprocess.run(WEBPUSH + [titulo, texto, "--tag", tag], capture_output=True, text=True, timeout=60)
        log(f"push {tag}: {' '.join((r.stdout + ' ' + r.stderr).split())[:300]}")
    threading.Thread(target=rodar, daemon=True).start()


def alguem_olhando() -> bool:
    """Painel aberto e visível (pediu /api/eventos há pouco) ou alguém digitando no tmux do PC."""
    if time.monotonic() - _push["olhar"] < ESPERA_MAX + 8:
        return True
    r = tmux("list-clients", "-t", f"{ALVO}:", "-F", "#{client_activity}")
    agora = time.time()
    return any(x.isdigit() and agora - int(x) < 45 for x in r.stdout.split())


def resumo_curto(texto: str, limite: int = 150) -> str:
    linhas = [re.sub(r"[*`#>_]|\[([^\]]*)\]\([^)]*\)", r"\1", l).strip() for l in texto.splitlines()]
    texto = " ".join(l for l in linhas if l)
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "…"


def vigiar() -> None:
    """Olha a sessão a cada 1,5 s e avisa no fim de cada turno e quando aparece pergunta nova."""
    sessao, vistos, pergunta, desde_perg = None, 0, "", 0.0
    while True:
        time.sleep(1.5)
        try:
            if not inscricoes_push():
                continue
            e = estado()
            conv = conversa_de(e["caminho"])
            total = len(conv.itens) if conv else 0
            if e["sessao"] != sessao:  # outra conversa: começa a contar daqui
                sessao, vistos = e["sessao"], total
            novos = conv.itens[vistos:total] if conv else []
            vistos = total
            assinatura = (e["pergunta"] or {}).get("assinatura", "")
            if assinatura != pergunta:
                pergunta, desde_perg = assinatura, time.monotonic()
            if alguem_olhando():
                desde_perg = 0.0 if assinatura else desde_perg  # já viu essa pergunta
                continue
            titulo = conv.titulo if conv else "Claude"
            prefs = prefs_push()
            if prefs["fim"] and any(i["t"] == "fim" for i in novos) and not e["pergunta"]:
                ultima = next((i["txt"] for i in reversed(conv.itens) if i["t"] == "a"), "")
                notificar("Claude terminou", f"{titulo}: {resumo_curto(ultima)}" if ultima else titulo, "fim")
            if prefs["pergunta"] and assinatura and desde_perg and time.monotonic() - desde_perg > 2:
                p = e["pergunta"]
                # a pergunta em si ("Do you want to create c.txt?"), sem o código que vem antes
                texto = next((b["txt"] for b in reversed(p.get("blocos") or []) if b.get("t") != "cod" and b.get("txt")),
                             p.get("pergunta") or "")
                notificar("Claude precisa de você", f"{titulo}: {resumo_curto(texto, 120)}", "pergunta")
                desde_perg = 0.0  # avisa uma vez por pergunta
        except Exception as erro:  # o vigia não pode morrer
            log(f"vigia: {erro!r}")


def versoes_claude() -> dict:
    """Versão do Claude aberto no tmux e a instalada (o instalador nativo troca o link
    ~/.local/bin/claude quando atualiza sozinho; o que já está aberto segue na antiga)."""
    def nome(caminho: Path) -> str:
        try:
            v = caminho.resolve(strict=True).name
        except OSError:
            return ""
        return v if re.fullmatch(r"\d+(\.\d+)+", v) else ""
    e = estado()
    em_uso = nome(Path(f"/proc/{e['pid']}/exe")) if e.get("pid") else ""
    instalada = nome(Path.home() / ".local" / "bin" / "claude")
    return {"em_uso": em_uso, "instalada": instalada, "aberto": bool(e["aberto"]),
            "atualizar": bool(em_uso and instalada and em_uso != instalada)}


def versao_pagina() -> str:
    return hex(max((ESTATICO / n).stat().st_mtime_ns for n in ("index.html", "app.js", "app.css")))[-10:]


def publico(e: dict, conv: Conversa | None, com_tela: bool) -> dict:
    """O que vai pra página (sem caminhos internos)."""
    saida = {k: e.get(k) for k in ("tmux", "aberto", "shell", "sessao", "pasta", "trabalhando",
                                    "iniciando", "pergunta", "colunas", "marca")}
    saida["titulo"] = conv.titulo if conv else ("Nova conversa" if e.get("aberto") else "Claude")
    saida["total"] = len(conv.itens) if conv else 0
    saida["versao"] = versao_pagina()
    if com_tela:
        saida["tela"] = e.get("tela", "")
        saida["tela_html"] = tela_colorida(e["pane"]) if e.get("pane") else []
        saida["links"] = links_da_tela(saida["tela"].split("\n"), int(e.get("colunas") or 80))[-3:]
        saida["marca_tela"] = e.get("marca_tela")
    return saida


# ---------------------------------------------------------------- ações no tmux

def exigir_claude_pronto(e: dict) -> None:
    if not e["tmux"]:
        raise Recusa(409, f"A sessão '{ALVO}' do tmux não existe. No PC: systemctl --user start claude-tmux")
    if not e["aberto"]:
        raise Recusa(409, "O Claude está fechado nesta sessão.")


def montar_mensagem(texto: str, caminhos: list[str]) -> str:
    imagens, outros = [], []
    for c in caminhos:
        alvo = Path(c).resolve()
        if alvo.parent.parent != ANEXOS.resolve() or not alvo.is_file():
            raise Recusa(400, "Um dos anexos não está mais no PC. Anexe de novo.")
        (imagens if alvo.suffix.lower() in EXT_IMAGEM else outros).append(alvo)
    if caminhos:
        ENVIADOS.guardar(chave_mensagem(texto), [f"{c.parent.name}/{c.name}" for c in imagens + outros])
    partes = [texto.strip()]
    # O Claude só transforma o caminho colado em imagem anexada quando ele vem separado
    # por espaço (como no arrastar de arquivo); depois de quebra de linha ele fica texto.
    if imagens:
        partes.append("Imagens: " + " ".join(str(c) for c in imagens))
    partes += [f"Anexo: {c}" for c in outros]
    return "\n\n".join(p for p in partes if p)


LINHA_CAIXA = re.compile(r"^─{10,}$")


def texto_da_caixa(pane: str) -> str:
    """O que está digitado na caixa de mensagem do Claude (entre as duas linhas do fim)."""
    cap = tmux("capture-pane", "-p", "-t", pane)
    linhas = [l.rstrip() for l in cap.stdout.split("\n")][-25:]
    bordas = [n for n, l in enumerate(linhas) if LINHA_CAIXA.match(l)]
    if len(bordas) < 2:
        return ""
    dentro = linhas[bordas[-2] + 1:bordas[-1]]
    if not dentro or not dentro[0].startswith("❯"):
        return ""
    # Sem tirar as linhas vazias: apagar uma quebra de linha também conta como mudança.
    return "\n".join([dentro[0][1:].rstrip()] + dentro[1:])


def limpar_caixa(pane: str) -> None:
    """Apaga o texto que sobrou na caixa (ex.: o Claude devolve ali o pedido interrompido),
    senão a mensagem nova sai grudada nele. Ctrl+U apaga uma linha por vez; se uma
    apertada não muda nada, o que aparece ali é só a dica cinza do Claude."""
    for _ in range(16):
        antes = texto_da_caixa(pane)
        if not antes.strip():
            return
        tmux("send-keys", "-t", pane, "C-u")
        time.sleep(0.12)
        if texto_da_caixa(pane) == antes:
            return


def enviar_texto(texto: str) -> None:
    e = estado(fresco=True)
    exigir_claude_pronto(e)
    if e["iniciando"]:
        raise Recusa(409, "O Claude ainda está abrindo. Espere um instante e mande de novo.")
    if e["pergunta"]:
        raise Recusa(409, "Tem uma pergunta aberta na tela. Responda ela primeiro.")
    limpar_caixa(e["pane"])
    # Colar com "bracketed paste": quebras de linha entram no texto em vez de enviar no meio.
    if tmux("load-buffer", "-b", "painel", "-", entrada=texto).returncode != 0:
        raise Recusa(500, "O tmux não aceitou o texto.")
    if tmux("paste-buffer", "-p", "-d", "-b", "painel", "-t", e["pane"]).returncode != 0:
        raise Recusa(500, "O tmux não conseguiu colar o texto.")
    time.sleep(0.25)
    tmux("send-keys", "-t", e["pane"], "Enter")


def apertar(tecla: str) -> None:
    if not TECLAS.match(tecla):
        raise Recusa(400, "Tecla não permitida.")
    e = estado(fresco=True)
    exigir_claude_pronto(e)
    tmux("send-keys", "-t", e["pane"], tecla)


def mover_no_menu(acao: str, alvo: dict, assinatura: str) -> None:
    """Anda com as setas até o alvo, conferindo a tela a cada passo, como quem usa o CLI.

    Lista: tocar na opção que já está com o cursor confirma (Enter); nas outras só move.
    Régua: move o ▲ até o nível e, com `confirmar`, aperta Enter (o padrão do CLI)."""
    for passo in range(40):
        e = estado(fresco=True)
        exigir_claude_pronto(e)
        p = e["pergunta"]
        if not p or p["assinatura"] != assinatura:
            raise Recusa(409, "O menu mudou na tela. Confira de novo.")
        if acao == "nivel":
            if p["tipo"] != "regua" or not 0 <= int(alvo.get("indice", -1)) < len(p["niveis"]):
                raise Recusa(400, "Nível inválido.")
            diferenca = int(alvo["indice"]) - p["atual"]
            if not diferenca:
                if alvo.get("confirmar"):  # o painel mostra só a régua: chegou no nível, confirma
                    tmux("send-keys", "-t", e["pane"], "Enter")
                return
            tecla = "Right" if diferenca > 0 else "Left"
        else:
            if p["tipo"] != "lista":
                raise Recusa(400, "Esse menu não tem opções pra tocar.")
            ops = p["opcoes"]
            atual = next((k for k, o in enumerate(ops) if o["sel"]), None)
            if p["numerado"]:
                k_alvo = next((k for k, o in enumerate(ops) if o["n"] == alvo.get("n")), None)
            else:
                k_alvo = next((k for k, o in enumerate(ops) if o["txt"] == alvo.get("txt")), None)
            if atual is None:
                raise Recusa(409, "Não achei o cursor do menu. Use as setas.")
            if k_alvo == atual:
                if passo == 0:
                    tmux("send-keys", "-t", e["pane"], "Enter")
                return
            if k_alvo is None:  # a opção rolou pra fora da tela: segue pelo número
                if not p["numerado"]:
                    raise Recusa(409, "Essa opção saiu da tela. Use as setas.")
                tecla = "Down" if int(alvo.get("n", 0)) > ops[atual]["n"] else "Up"
            else:
                tecla = "Down" if k_alvo > atual else "Up"
        tmux("send-keys", "-t", e["pane"], tecla)
        time.sleep(0.15)
    raise Recusa(409, "Não consegui chegar nessa opção. Use as setas.")


def digitar(texto: str, enter: bool) -> None:
    """Texto solto dentro de um menu (ex.: a opção "outra resposta" de uma pergunta)."""
    e = estado(fresco=True)
    exigir_claude_pronto(e)
    tmux("send-keys", "-t", e["pane"], "-l", texto)
    if enter:
        time.sleep(0.15)
        tmux("send-keys", "-t", e["pane"], "Enter")


# ---------------------------------------------------------------- conversas e sessão

_resumos: dict[Path, tuple[tuple, dict | None]] = {}
_resumos_trava = threading.Lock()


def _linhas_json(bloco: bytes, pular_primeira: bool):
    partes = bloco.split(b"\n")
    for parte in partes[1:] if pular_primeira else partes:
        try:
            yield json.loads(parte)
        except ValueError:
            continue


def resumo_sessao(caminho: Path) -> dict | None:
    """Título, pasta e última mensagem de uma conversa, lendo só o começo e o fim do .jsonl."""
    try:
        st = caminho.stat()
    except OSError:
        return None
    chave = (st.st_mtime_ns, st.st_size)
    with _resumos_trava:
        guardado = _resumos.get(caminho)
    if guardado and guardado[0] == chave:
        return guardado[1]
    cabeca_tam = 96 * 1024
    with open(caminho, "rb") as f:
        cabeca = f.read(cabeca_tam)
        cauda = b""
        if st.st_size > cabeca_tam:
            f.seek(max(cabeca_tam, st.st_size - 256 * 1024))
            cauda = f.read()
    titulo_ia = titulo_proprio = ultima = primeiro = pasta = ""
    for d in [*_linhas_json(cabeca, False), *_linhas_json(cauda, True)]:
        tipo = d.get("type")
        if not pasta and d.get("cwd"):
            pasta = d["cwd"]
        if tipo == "ai-title":
            titulo_ia = d.get("aiTitle") or titulo_ia
        elif tipo == "custom-title":
            titulo_proprio = d.get("customTitle") or titulo_proprio
        elif tipo == "last-prompt":
            ultima = d.get("lastPrompt") or ultima
        elif tipo == "user" and not primeiro and not d.get("isMeta") and not d.get("isSidechain"):
            c = (d.get("message") or {}).get("content")
            if isinstance(c, str) and c.strip() and not c.lstrip().startswith(("<", "[")):
                primeiro = " ".join(c.split())
    resultado = None
    if primeiro or titulo_ia or titulo_proprio:
        resultado = {"id": caminho.stem, "titulo": titulo_proprio or titulo_ia or primeiro[:70],
                     "pasta": curto(pasta), "cwd": pasta, "ultima": " ".join(ultima.split())[:160],
                     "quando": int(st.st_mtime * 1000)}
    with _resumos_trava:
        _resumos[caminho] = (chave, resultado)
    return resultado


def abertas_agora() -> dict[str, int]:
    """Conversas abertas em algum Claude rodando agora (id da conversa -> pid)."""
    abertas = {}
    for arq in (CLAUDE / "sessions").glob("*.json"):
        try:
            info = json.loads(arq.read_text())
            pid = int(info.get("pid") or arq.stem)
            if Path(f"/proc/{pid}/comm").read_text().strip() == "claude" and info.get("sessionId"):
                abertas[info["sessionId"]] = pid
        except (OSError, ValueError):
            continue
    return abertas


def listar_sessoes(limite: int = 80) -> list[dict]:
    arquivos = sorted((CLAUDE / "projects").glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    abertas = abertas_agora()
    aqui = estado().get("sessao")
    saida = []
    for caminho in arquivos:
        r = resumo_sessao(caminho)
        if r:
            item = {k: v for k, v in r.items() if k != "cwd"}
            if r["id"] in abertas and r["id"] != aqui:
                item["outro"] = True  # aberta em outro terminal (Konsole, Termius...)
            saida.append(item)
        if len(saida) >= limite:
            break
    return saida


def esperar(condicao, segundos: float) -> dict:
    limite = time.monotonic() + segundos
    while True:
        e = estado(fresco=True)
        if condicao(e) or time.monotonic() > limite:
            return e
        time.sleep(0.3)


def rodar_no_shell(e: dict, comando: str) -> None:
    tmux("send-keys", "-t", e["pane"], "C-u")
    tmux("send-keys", "-t", e["pane"], "-l", comando)
    tmux("send-keys", "-t", e["pane"], "Enter")


def acao_sessao(acao: str, sid: str = "") -> None:
    """Abrir, fechar, começar do zero ou retomar uma conversa na sessão do tmux.

    Retomar sai do Claude atual (/exit) e abre o escolhido com `claude --resume <id>`
    na pasta daquela conversa, o que funciona pra conversa de qualquer projeto."""
    if acao == "ligar":
        if estado(fresco=True)["tmux"]:
            raise Recusa(409, "A sessão do tmux já está ligada.")
        # O mesmo que o claude-tmux.service faz no boot. Direto no tmux porque o serviço continua
        # "ativo" enquanto o servidor do tmux tiver qualquer outra sessão, e aí start não faz nada.
        # 79x70 fixo: sem nenhum terminal ligado o tmux usaria 80x24, curto demais pros menus do Claude
        tmux("new-session", "-d", "-s", ALVO, "-x", "79", "-y", "70", "-c", PASTA_INICIAL,
             f"{SHELL_LOGIN} -lic {shlex.quote(f'{CMD_CLAUDE}; exec {SHELL_LOGIN} -l')}")
        if not esperar(lambda e: e["tmux"], 10)["tmux"]:
            raise Recusa(500, "Não consegui ligar a sessão do tmux. No PC: systemctl --user status claude-tmux")
        esperar(lambda e: e["aberto"], 10)
        return
    alvo_cwd = ""
    reiniciar = acao == "reiniciar"  # versão nova do Claude: sai e volta na mesma conversa
    if reiniciar:
        sid = estado(fresco=True)["sessao"] or ""
        if not sid:
            raise Recusa(409, "O Claude não está aberto numa conversa.")
        acao = "retomar"
    if acao == "retomar":
        if not ID_SESSAO.match(sid):
            raise Recusa(400, "Conversa inválida.")
        achados = list((CLAUDE / "projects").glob(f"*/{sid}.jsonl"))
        resumo = resumo_sessao(achados[0]) if achados else None
        if not resumo:
            raise Recusa(404, "Não achei essa conversa no PC.")
        alvo_cwd = resumo["cwd"]
        if sid in abertas_agora() and sid != estado(fresco=True)["sessao"]:
            raise Recusa(409, "Essa conversa está aberta em outro terminal. Feche lá antes, "
                              "senão os dois Claudes escrevem na mesma conversa.")
        if not alvo_cwd or not Path(alvo_cwd).is_dir():
            raise Recusa(409, f"A pasta dessa conversa não existe mais ({resumo['pasta'] or '?'}).")
    elif acao not in ("fechar", "nova", "continuar"):
        raise Recusa(400, "Ação desconhecida.")

    e = estado(fresco=True)
    if not e["tmux"]:
        raise Recusa(409, "A sessão do tmux não existe. Toque em Ligar sessão.")
    if e["aberto"]:
        if acao == "retomar" and e["sessao"] == sid and not reiniciar:
            return
        if e["pergunta"]:
            raise Recusa(409, "Tem uma pergunta aberta na tela. Responda ou cancele antes.")
        if e["trabalhando"]:
            raise Recusa(409, "O Claude está trabalhando. Pare ele primeiro (botão esc) e tente de novo.")
        if acao == "continuar":
            return
        if acao == "nova":
            enviar_texto("/clear")
            return
        enviar_texto("/exit")
        e = esperar(lambda e: not e["aberto"], 12)
        if e["aberto"]:
            raise Recusa(500, "O Claude não fechou. Confira a tela do terminal.")
        if acao == "fechar":
            return
        e = esperar(lambda e: e["shell"], 4)
    elif acao == "fechar":
        return
    if not e["shell"]:
        raise Recusa(409, "O terminal está com outro programa aberto. Confira a tela do terminal.")
    if acao == "retomar":
        comando = f"cd -- {shlex.quote(alvo_cwd)} && {CMD_CLAUDE} --resume {sid}"
    elif acao == "continuar":
        comando = f"{CMD_CLAUDE} -c"
    else:
        comando = CMD_CLAUDE
    rodar_no_shell(e, comando)
    if not esperar(lambda e: e["aberto"], 12)["aberto"]:
        raise Recusa(500, "Mandei abrir, mas o Claude não apareceu. Confira a tela do terminal.")


COMANDOS = [
    ("/compact", "Resumir a conversa pra liberar contexto", True),
    ("/context", "Quanto do contexto está ocupado", False),
    ("/usage", "Custo da sessão e uso do plano", False),
    ("/model", "Trocar o modelo", False),
    ("/effort", "Mudar o nível de esforço", False),
    ("/fast", "Ligar ou desligar o modo rápido", False),
    ("/plan", "Modo de planejamento", False),
    ("/rename", "Renomear esta conversa", True),
    ("/rewind", "Voltar a um ponto anterior", False),
    ("/btw", "Pergunta rápida por fora da conversa", True),
    ("/export", "Exportar a conversa", False),
    ("/status", "Status do Claude Code", False),
    ("/doctor", "Diagnóstico da instalação", False),
    ("/login", "Entrar de novo (login expirado)", False),
    ("/clear", "Começar uma conversa nova", False),
    ("/resume", "Escolher outra conversa", False),
    ("/exit", "Fechar o Claude", False),
]


def listar_comandos() -> list[dict]:
    saida = [{"cmd": c, "desc": d, "arg": a} for c, d, a in COMANDOS]
    for skill in sorted((CLAUDE / "skills").glob("*/SKILL.md")):
        try:
            texto = skill.read_text()[:3000]
        except OSError:
            continue
        m = re.search(r"^description:\s*(.+)$", texto, re.M)
        desc = (m.group(1).strip().strip('"') if m else "")
        desc = re.split(r"(?<=[.!?])\s", desc)[0][:90]
        saida.append({"cmd": "/" + skill.parent.name, "desc": desc, "arg": True, "skill": True})
    return saida


# ---------------------------------------------------------------- servidor HTTP

NOME_ANEXO = re.compile(r"^\d{4}-\d{2}-\d{2}/[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def salvar_anexo(nome: str, leitor, tamanho: int) -> dict:
    agora = datetime.now()
    pasta = ANEXOS / agora.strftime("%Y-%m-%d")
    pasta.mkdir(parents=True, exist_ok=True)
    base = re.sub(r"[^A-Za-z0-9._-]", "_", Path(nome).name).lstrip("._")[:80] or "arquivo"
    alvo = pasta / f"{agora:%H%M%S}-{base}"
    n = 2
    while alvo.exists():
        alvo = pasta / f"{agora:%H%M%S}-{n}-{base}"
        n += 1
    parcial = alvo.with_name(alvo.name + ".parcial")
    restante = tamanho
    with open(parcial, "wb") as f:
        while restante > 0:
            bloco = leitor.read(min(1024 * 1024, restante))
            if not bloco:
                break
            f.write(bloco)
            restante -= len(bloco)
    if restante:
        parcial.unlink(missing_ok=True)
        raise Recusa(400, "O envio chegou incompleto. Tente de novo.")
    parcial.rename(alvo)
    tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
    return {"caminho": str(alvo), "url": f"/api/anexo/{alvo.parent.name}/{alvo.name}", "tipo": tipo,
            "tam": tamanho, "nome": alvo.name}


class Painel(BaseHTTPRequestHandler):
    server_version = "painel"

    # -- respostas
    def _bytes(self, codigo: int, dados: bytes, tipo: str, cache: str = "no-store") -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(dados)

    def _json(self, codigo: int, obj) -> None:
        self._bytes(codigo, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _erro(self, codigo: int, mensagem: str) -> None:
        self._json(codigo, {"erro": mensagem})

    # -- quem pode
    def _autorizado(self, muda: bool) -> bool:
        if self.headers.get("Tailscale-User-Login") != LOGIN:
            return False
        if self.headers.get("Host") not in HOSTS_OK:
            return False
        if muda:
            # Página de outro site aberta no celular não consegue mandar este cabeçalho
            # sem a permissão de CORS, que este servidor nunca dá.
            if self.headers.get("X-Painel") != "1":
                return False
            if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
                return False
            origem = self.headers.get("Origin")
            if origem and origem not in ORIGENS_OK:
                return False
        return True

    def _corpo_json(self) -> dict:
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho <= 0 or tamanho > 5 * 1024 * 1024:
            raise Recusa(400, "Pedido vazio ou grande demais.")
        try:
            return json.loads(self.rfile.read(tamanho))
        except ValueError:
            raise Recusa(400, "Pedido inválido.") from None

    # -- rotas
    def do_GET(self) -> None:
        if not self._autorizado(muda=False):
            return self._erro(403, "Sem permissão.")
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path in ARQUIVOS_ESTATICOS:
                return self._estatico(ARQUIVOS_ESTATICOS[url.path])
            if url.path == "/api/conversa":
                return self._conversa(q)
            if url.path == "/api/eventos":
                return self._eventos(q)
            if url.path == "/api/sessoes":
                e = estado()
                return self._json(200, {"atual": e["sessao"], "sessoes": listar_sessoes()})
            if url.path == "/api/comandos":
                return self._json(200, {"comandos": listar_comandos()})
            if url.path.startswith("/api/saida/"):
                return self._saida(unquote(url.path[len("/api/saida/"):]), q)
            if url.path.startswith("/api/anexo/"):
                return self._anexo(unquote(url.path[len("/api/anexo/"):]))
            if url.path == "/api/claude":
                return self._json(200, versoes_claude())
            if url.path == "/api/push/chave":
                return self._json(200, {"chave": chave_push(), "inscrito": len(inscricoes_push()), "prefs": prefs_push()})
            if url.path == "/api/entregas":
                return self._json(200, {"entregas": ENTREGAS_REG.lista()})
            if m := re.fullmatch(r"/api/entrega/([A-Za-z0-9_-]{6,16})(/previa)?", url.path):
                return self._entrega(m.group(1), bool(m.group(2)), "baixar" in q)
            return self._erro(404, "Não encontrado.")
        except Recusa as r:
            return self._erro(r.codigo, r.mensagem)

    do_HEAD = do_GET  # o Safari pergunta o tamanho do vídeo antes de tocar

    def do_POST(self) -> None:
        if not self._autorizado(muda=True):
            return self._erro(403, "Sem permissão.")
        url = urlparse(self.path)
        try:
            corpo = self._corpo_json()
            if url.path == "/api/enviar":
                caminhos = [str(c) for c in corpo.get("anexos") or []][:20]
                texto = montar_mensagem(str(corpo.get("texto") or ""), caminhos)
                if not texto:
                    raise Recusa(400, "Mensagem vazia.")
                enviar_texto(texto)
            elif url.path == "/api/sessao":
                acao_sessao(str(corpo.get("acao") or ""), str(corpo.get("id") or ""))
            elif url.path == "/api/menu":
                mover_no_menu(str(corpo.get("acao") or ""), corpo.get("alvo") or {},
                              str(corpo.get("assinatura") or ""))
            elif url.path == "/api/tecla":
                apertar(str(corpo.get("tecla") or ""))
            elif url.path == "/api/push/oculto":  # a página foi pro fundo: avisos voltam a valer já
                _push["olhar"] = 0.0
                return self._json(200, {"ok": True})
            elif url.path == "/api/push/inscrever":
                guardar_inscricao(corpo.get("inscricao") or {})
                notificar("Notificações ligadas", "É assim que o painel avisa quando o Claude terminar ou precisar de você.", "teste")
            elif url.path == "/api/push/prefs":
                prefs = guardar_prefs(corpo)
                log(f"{url.path} {json.dumps(prefs)}")
                return self._json(200, {"ok": True, "prefs": prefs})
            elif url.path == "/api/push/sair":
                tirar_inscricao(str(corpo.get("endpoint") or ""))

            elif url.path == "/api/digitar":
                texto = str(corpo.get("texto") or "")
                if not texto.strip():
                    raise Recusa(400, "Texto vazio.")
                digitar(texto, bool(corpo.get("enter")))
            else:
                raise Recusa(404, "Não encontrado.")
            log(f"{url.path} {json.dumps(corpo, ensure_ascii=False)[:200]}")
            time.sleep(0.15)
            e = estado(fresco=True)
            return self._json(200, {"ok": True, "estado": publico(e, conversa_de(e["caminho"]), False)})
        except Recusa as r:
            return self._erro(r.codigo, r.mensagem)

    def do_PUT(self) -> None:
        if not self._autorizado(muda=True):
            return self._erro(403, "Sem permissão.")
        url = urlparse(self.path)
        if url.path != "/api/anexo":
            return self._erro(404, "Não encontrado.")
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho <= 0 or tamanho > LIMITE_ANEXO:
            return self._erro(413, "Arquivo vazio ou maior que 2 GB.")
        nome = unquote(parse_qs(url.query).get("nome", ["arquivo"])[0])
        try:
            salvo = salvar_anexo(nome, self.rfile, tamanho)
        except Recusa as r:
            return self._erro(r.codigo, r.mensagem)
        log(f"anexo {salvo['caminho']} ({tamanho} bytes)")
        return self._json(200, salvo)

    def do_OPTIONS(self) -> None:  # sem CORS: nenhuma origem de fora passa da pré-checagem
        self._erro(405, "Não permitido.")

    # -- implementações
    def _estatico(self, nome: str) -> None:
        caminho = ESTATICO / nome
        try:
            dados = caminho.read_bytes()
        except OSError:
            return self._erro(404, "Não encontrado.")
        tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
        if nome.endswith(".webmanifest"):
            tipo = "application/manifest+json"
        if tipo.startswith("text/") or tipo.endswith(("javascript", "json")):
            tipo += "; charset=utf-8"
        self._bytes(200, dados, tipo, cache="no-cache")

    def _conversa(self, q: dict) -> None:
        e = estado()
        conv = conversa_de(e["caminho"])
        itens = conv.itens if conv else []
        if "antes" in q:
            antes = max(0, min(int(q["antes"][0]), len(itens)))
            inicio = max(0, antes - int(q.get("limite", [PRIMEIROS])[0]))
            parte = itens[inicio:antes]
        else:
            inicio = max(0, len(itens) - PRIMEIROS)
            parte = itens[inicio:]
        self._json(200, {"estado": publico(e, conv, "tela" in q), "inicio": inicio, "itens": parte})

    def _eventos(self, q: dict) -> None:
        """Segura a resposta até ter item novo, mudança de estado ou ESPERA_MAX segundos."""
        sessao = q.get("sessao", [""])[0]
        desde = int(q.get("desde", ["0"])[0])
        marca = q.get("marca", [""])[0]
        com_tela = "tela" in q
        marca_tela = q.get("marca_tela", [""])[0]
        _push["olhar"] = time.monotonic()
        limite = time.monotonic() + ESPERA_MAX
        while True:
            e = estado()
            conv = conversa_de(e["caminho"])
            total = len(conv.itens) if conv else 0
            mudou = ((e["sessao"] or "") != sessao or total > desde or e["marca"] != marca
                     or (com_tela and e.get("marca_tela") != marca_tela))
            if mudou or time.monotonic() > limite:
                break
            time.sleep(0.5)
        resposta = {"estado": publico(e, conv, com_tela)}
        if (e["sessao"] or "") != sessao:
            resposta["reiniciar"] = True
        elif conv and total > desde:
            resposta["itens"] = conv.itens[desde:]
        self._json(200, resposta)

    def _saida(self, fid: str, q: dict) -> None:
        e = estado()
        conv = conversa_de(e["caminho"])
        if not conv:
            raise Recusa(404, "Sem conversa aberta.")
        self._json(200, conv.detalhe(fid))

    def _anexo(self, rel: str) -> None:
        if not NOME_ANEXO.match(rel):
            raise Recusa(404, "Não encontrado.")
        caminho = ANEXOS / rel
        try:
            dados = caminho.read_bytes()
        except OSError:
            raise Recusa(404, "Não encontrado.") from None
        self._bytes(200, dados, mimetypes.guess_type(caminho.name)[0] or "application/octet-stream",
                    cache="private, max-age=86400")

    def _entrega(self, eid: str, previa: bool, baixar: bool) -> None:
        d = ENTREGAS_REG.item(eid)
        rel = d and (d.get("previa") if previa else d.get("rel"))
        if not rel or not NOME_ANEXO.match(rel):
            raise Recusa(404, "Esse arquivo não está mais no PC.")
        caminho = ENTREGAS / rel
        if previa:
            return self._arquivo(caminho, "image/jpeg", "previa.jpg", False)
        return self._arquivo(caminho, d.get("mime") or "application/octet-stream", d.get("nome") or caminho.name, baixar)

    def _arquivo(self, caminho: Path, mime: str, nome: str, baixar: bool) -> None:
        """Manda o arquivo aos pedaços, com suporte a Range (sem ele o Safari não toca vídeo)."""
        try:
            f = open(caminho, "rb")
        except OSError:
            raise Recusa(404, "Esse arquivo não está mais no PC.") from None
        with f:
            total = os.fstat(f.fileno()).st_size
            ini, fim, codigo = 0, total - 1, 200
            faixa = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
            if faixa and any(faixa.groups()):
                a, b = faixa.groups()
                ini, fim = (max(0, total - int(b)), total - 1) if a == "" else (int(a), min(int(b), total - 1) if b else total - 1)
                if ini > fim or ini >= total:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                codigo = 206
            self.send_response(codigo)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(max(0, fim - ini + 1)))
            self.send_header("Accept-Ranges", "bytes")
            if codigo == 206:
                self.send_header("Content-Range", f"bytes {ini}-{fim}/{total}")
            self.send_header("Cache-Control", "private, max-age=604800")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Disposition", f"{'attachment' if baixar else 'inline'}; filename*=UTF-8''{quote(nome)}")
            if mime.split(";")[0] in ("text/html", "image/svg+xml", "application/xhtml+xml", "text/xml", "application/xml"):
                # Página entregue roda isolada: sem script e sem a origem do painel (não alcança a API).
                self.send_header("Content-Security-Policy", "sandbox allow-popups allow-popups-to-escape-sandbox")
            self.end_headers()
            if self.command == "HEAD":
                return
            f.seek(ini)
            restante = fim - ini + 1
            while restante > 0:
                bloco = f.read(min(256 * 1024, restante))
                if not bloco:
                    break
                try:
                    self.wfile.write(bloco)
                except (BrokenPipeError, ConnectionResetError):
                    return
                restante -= len(bloco)

    def log_message(self, fmt: str, *args) -> None:
        pass


def log(msg: str) -> None:
    with open(RAIZ / "logs" / "painel.log", "a") as f:
        f.write(f"{datetime.now():%F %T} {msg}\n")


if __name__ == "__main__":
    try:
        LOGIN, HOST_TS = identidade()
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as erro:
        sys.exit(f"painel: não consegui ler a identidade da Tailscale ({erro}); sem ela não atendo ninguém")
    HOSTS_OK = {f"{HOST_TS}:{PORTA_TS}", HOST_TS}
    ORIGENS_OK = {f"https://{HOST_TS}:{PORTA_TS}"}
    (RAIZ / "logs").mkdir(exist_ok=True)
    ANEXOS.mkdir(exist_ok=True)
    log(f"no ar em 127.0.0.1:{PORTA}, sessão '{ALVO}', só para {LOGIN}")
    print(f"painel em 127.0.0.1:{PORTA} (sessão tmux '{ALVO}', só {LOGIN})", flush=True)
    threading.Thread(target=vigiar, daemon=True, name="vigia").start()
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(("127.0.0.1", PORTA), Painel).serve_forever()
