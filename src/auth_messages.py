# -*- coding: utf-8 -*-
"""Textos do fluxo de senha e sessão."""
from __future__ import annotations


def _name(first_name: str = "") -> str:
    return (first_name or "").strip()


def build_password_prompt(first_name: str = "") -> str:
    name = _name(first_name)
    who = f", {name}" if name else ""
    return (
        f"🔐 *Acesso protegido{who}*\n\n"
        "Toque em *Responder* e digite a senha no campo abaixo.\n"
        "Por segurança, eu *apago a mensagem da senha* assim que receber.\n\n"
        "Esqueceu a senha? Digite *esqueci a senha* — o admin recebe o pedido "
        "no grupo *Robôs Sous Tec*.\n\n"
        "_O Telegram não oferece caixa de senha oculta para bots — "
        "por isso apagamos o que você digitar._"
    )


def build_password_ok(first_name: str = "") -> str:
    name = _name(first_name)
    if name:
        return (
            f"✅ Pronto, *{name}*! Acesso liberado. Pode usar o menu normalmente.\n\n"
            "_Quando terminar, toque em *🔒 Encerrar sessão*._"
        )
    return (
        "✅ Pronto! Acesso liberado. Pode usar o menu normalmente.\n\n"
        "_Quando terminar, toque em *🔒 Encerrar sessão*._"
    )


def build_password_wrong() -> str:
    return "❌ Senha incorreta. Tente de novo."


def build_locked_message() -> str:
    return (
        "🔒 *Sessão encerrada.*\n\n"
        "Limpei o histórico desta conversa para não deixar vestígios.\n"
        "Para entrar de novo, digite a senha de acesso."
    )


def build_session_expired_message() -> str:
    return (
        "⏰ *Sessão expirada.*\n\n"
        "Passaram-se alguns minutos *sem uso* e limpei o histórico "
        "para não deixar vestígios.\n"
        "Para entrar de novo, digite a senha de acesso."
    )


def build_password_help_received() -> str:
    return (
        "📬 *Pedido enviado ao admin.*\n\n"
        "Assim que ele *liberar*, eu te aviso aqui e você escolhe uma *senha nova*.\n"
        "_Enquanto isso, aguarde — não precisa repetir o pedido._"
    )


def build_password_reset_approved() -> str:
    return (
        "✅ *Troca de senha liberada!*\n\n"
        "Digite agora a *nova senha* (aí eu peço de novo pra confirmar).\n"
        "_Mínimo 4 caracteres — diferente da senha padrão do robô._"
    )


def build_password_reset_denied() -> str:
    return (
        "❌ *Pedido de troca de senha negado* pelo admin.\n\n"
        "Se ainda precisar, digite *esqueci a senha* de novo."
    )


def build_password_reset_prompt_confirm() -> str:
    return "🔁 Digite a *mesma senha* de novo para confirmar."


def build_password_reset_mismatch() -> str:
    return "⚠️ As senhas não batem. Digite a *nova senha* de novo."


def build_password_reset_too_short() -> str:
    return "⚠️ A senha precisa ter pelo menos *4* caracteres. Tente de novo."


def build_password_changed_ok(first_name: str = "") -> str:
    name = _name(first_name)
    if name:
        return (
            f"✅ Senha atualizada, *{name}*! Acesso liberado.\n\n"
            "_Quando terminar, toque em *🔒 Encerrar sessão*._"
        )
    return (
        "✅ Senha atualizada! Acesso liberado.\n\n"
        "_Quando terminar, toque em *🔒 Encerrar sessão*._"
    )
