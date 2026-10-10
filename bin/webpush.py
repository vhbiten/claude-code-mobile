#!/usr/bin/env python3
"""Notificação no iPhone sem app: Web Push pro painel instalado na Tela de Início.

    webpush.py "título" ["texto"] [--url /] [--tag nome]   manda pra todas as inscrições
    webpush.py --chave                                      chave pública (VAPID) pra página
    webpush.py --testar                                     confere a cifragem com o exemplo do RFC 8291

A mensagem vai cifrada de ponta a ponta (RFC 8291, aes128gcm): o serviço de push da Apple só
repassa bytes que não consegue ler. O pedido é assinado com a chave VAPID (RFC 8292), gerada
na primeira vez em config/vapid.json. As inscrições ficam em config/push-inscricoes.json (o
servidor do painel grava); inscrição que o serviço diz que morreu (404/410) é apagada.
Roda com o Python da .venv do projeto (o install.sh instala o pacote cryptography nela).
"""
import base64
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CONFIG = Path(os.environ.get("PAINEL_CONFIG", Path(__file__).resolve().parent.parent / "config"))
VAPID = CONFIG / "vapid.json"
INSCRICOES = CONFIG / "push-inscricoes.json"
CONTATO = os.environ.get("PAINEL_CONTATO", "https://github.com/vhbiten/claude-code-mobile")  # o "sub" do VAPID


def b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def ponto(chave: ec.EllipticCurvePublicKey) -> bytes:
    return chave.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def hkdf(sal: bytes, ikm: bytes, info: bytes, tamanho: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=tamanho, salt=sal, info=info).derive(ikm)


def chave_vapid() -> ec.EllipticCurvePrivateKey:
    if VAPID.exists():
        return ec.derive_private_key(int.from_bytes(de_b64(json.loads(VAPID.read_text())["privada"]), "big"), ec.SECP256R1())
    privada = ec.generate_private_key(ec.SECP256R1())
    CONFIG.mkdir(parents=True, exist_ok=True)
    VAPID.touch(mode=0o600)
    VAPID.write_text(json.dumps({"privada": b64(privada.private_numbers().private_value.to_bytes(32, "big")),
                                 "publica": b64(ponto(privada.public_key()))}))
    return privada


def cifrar(texto: bytes, ua_publica: bytes, segredo: bytes,
           privada: ec.EllipticCurvePrivateKey | None = None, sal: bytes | None = None) -> bytes:
    """Corpo aes128gcm do RFC 8291 (um registro só). `privada` e `sal` fixos só no teste."""
    privada = privada or ec.generate_private_key(ec.SECP256R1())
    sal = sal or os.urandom(16)
    as_publica = ponto(privada.public_key())
    compartilhado = privada.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_publica))
    ikm = hkdf(segredo, compartilhado, b"WebPush: info\x00" + ua_publica + as_publica, 32)
    cek = hkdf(sal, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf(sal, ikm, b"Content-Encoding: nonce\x00", 12)
    cifrado = AESGCM(cek).encrypt(nonce, texto + b"\x02", None)
    return sal + struct.pack("!IB", 4096, len(as_publica)) + as_publica + cifrado


def jwt_vapid(endpoint: str, privada: ec.EllipticCurvePrivateKey) -> str:
    u = urlparse(endpoint)
    cabeca = b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    corpo = b64(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": CONTATO},
                           separators=(",", ":")).encode())
    r, s = decode_dss_signature(privada.sign(f"{cabeca}.{corpo}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{cabeca}.{corpo}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def mandar(inscricao: dict, mensagem: dict, privada: ec.EllipticCurvePrivateKey) -> tuple[int, str]:
    corpo = cifrar(json.dumps(mensagem, ensure_ascii=False).encode(), de_b64(inscricao["keys"]["p256dh"]),
                   de_b64(inscricao["keys"]["auth"]))
    pedido = urllib.request.Request(inscricao["endpoint"], data=corpo, method="POST", headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "86400",
        "Urgency": "high",  # sem "Topic": a Apple recusou "teste" com BadWebPushTopic; quem substitui é a tag
        "Authorization": f"vapid t={jwt_vapid(inscricao['endpoint'], privada)}, k={b64(ponto(privada.public_key()))}"})
    try:
        with urllib.request.urlopen(pedido, timeout=15) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:  # a Apple diz o motivo no corpo: {"reason": "BadJwtToken"}
        return e.code, e.read(300).decode(errors="replace").strip()


def inscricoes() -> list[dict]:
    try:
        return json.loads(INSCRICOES.read_text())
    except (OSError, ValueError):
        return []


def notificar(titulo: str, texto: str = "", url: str = "/", tag: str = "painel") -> tuple[int, int]:
    """Manda pra todas as inscrições. Devolve (entregues, total)."""
    lista = inscricoes()
    if not lista:
        return 0, 0
    privada = chave_vapid()
    mensagem = {"titulo": titulo, "texto": texto, "url": url, "tag": tag}
    vivas, ok = [], 0
    for i in lista:
        try:
            codigo, motivo = mandar(i, mensagem, privada)
        except (OSError, KeyError, ValueError) as e:
            print(f"webpush: falhou ({e})", file=sys.stderr)
            vivas.append(i)
            continue
        if codigo in (404, 410):  # o iPhone desinstalou o app ou tirou a permissão
            continue
        vivas.append(i)
        if 200 <= codigo < 300:
            ok += 1
        else:
            print(f"webpush: o serviço respondeu {codigo} {motivo}", file=sys.stderr)
    if len(vivas) != len(lista):
        INSCRICOES.write_text(json.dumps(vivas))
    return ok, len(lista)


def testar() -> None:
    """Exemplo do RFC 8291, seção 5: com as mesmas chaves e o mesmo sal o corpo tem que bater."""
    priv = ec.derive_private_key(int.from_bytes(de_b64("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
    corpo = cifrar(b"When I grow up, I want to be a watermelon",
                   de_b64("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"),
                   de_b64("BTBZMqHH6r4Tts7J_aSIgg"), priv, de_b64("DGv6ra1nlYgDCS1FRnbzlw"))
    esperado = ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wE"
                "qKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")
    print("cifragem: ok (bate com o RFC 8291)" if b64(corpo) == esperado else f"cifragem: DIFERENTE\n{b64(corpo)}")
    privada = ec.generate_private_key(ec.SECP256R1())
    token = jwt_vapid("https://web.push.apple.com/abc", privada)
    cab, corpo_jwt, ass = token.split(".")
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    sig = de_b64(ass)
    privada.public_key().verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                                f"{cab}.{corpo_jwt}".encode(), ec.ECDSA(hashes.SHA256()))
    print("vapid: ok (assinatura confere)", json.loads(de_b64(corpo_jwt)))


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if args else 2
    if args[0] == "--chave":
        print(b64(ponto(chave_vapid().public_key())))
        return 0
    if args[0] == "--testar":
        testar()
        return 0
    url, tag, livres = "/", "painel", []
    it = iter(args)
    for a in it:
        if a == "--url":
            url = next(it, "/")
        elif a == "--tag":
            tag = next(it, "painel")
        else:
            livres.append(a)
    ok, total = notificar(livres[0], livres[1] if len(livres) > 1 else "", url, tag)
    if not total:
        print("webpush: nenhum iPhone inscrito (ative no painel aberto pela Tela de Início)", file=sys.stderr)
        return 3
    print(f"webpush: {ok}/{total} entregue(s) ao serviço de push")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
