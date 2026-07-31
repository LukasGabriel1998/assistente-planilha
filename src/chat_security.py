# -*- coding: utf-8 -*-
"""Senha de acesso, sessão com TTL e limpeza de mensagens (padrão Line S2)."""
from __future__ import annotations

import collections
import hmac
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

import requests

from src import admin_inbox as inbox
from src import auth_messages
from src.password_resets import clear as reset_clear
from src.password_resets import get as reset_get
from src.password_resets import set_state as reset_set
from src.runtime_paths import runtime_file
from src.user_passwords import set_password as user_set_password
from src.user_passwords import verify_password as user_verify_password

WIPE_LOOKBACK = 1500
WIPE_BATCH = 100
MESSAGE_LOG_MAX = 1200

MENU_ENCERRAR_SESSAO = "🔒 Encerrar sessão"

PASSWORD_FORCE_REPLY = {"force_reply": True, "selective": True}

FORGOT_PASSWORD_PHRASES = frozenset(
    {
        "esqueci a senha",
        "esqueci senha",
        "esqueci",
        "forgot",
        "forgot password",
        "/esqueci",
        "perdi a senha",
        "ajuda senha",
        "trocar senha",
        "mudar senha",
    }
)

LOCK_WORDS = frozenset(
    {
        "/logout",
        "/lock",
        "logout",
        "lock",
        "encerrar sessao",
        "encerrar sessão",
        "sair",
        "fechar sessao",
        "fechar sessão",
    }
)

SendFn = Callable[..., int | None]
DeleteFn = Callable[..., bool]
EditFn = Callable[..., bool]
HubFn = Callable[[int | str], bool]
NotifyAdminFn = Callable[[str, dict | None], bool]
ClearStateFn = Callable[[int | str], None]
MenuKeyboardFn = Callable[[], dict]


class ChatSecurity:
  def __init__(self, project_dir: Path) -> None:
    self.project_dir = project_dir
    self.unlocked_until: dict[int | str, float] = {}
    self.password_reset_await: dict[int | str, dict[str, Any]] = {}
    self._message_log: dict[str, list[int]] = collections.defaultdict(list)
    self._durable_message_log: dict[str, list[int]] = collections.defaultdict(list)
    self._chat_msg_range: dict[str, list[int]] = {}
    self._message_log_lock = threading.Lock()
    self._session_end_lock = threading.Lock()
    self._recent_ttl_ends: dict[str, float] = {}
    self._last_password_prompt_at: dict[str, float] = {}
    self._sessions_file = runtime_file(project_dir, "bot_sessions.json")
    self._base_url = ""
    self._send_message: SendFn | None = None
    self._delete_message: DeleteFn | None = None
    self._edit_message: EditFn | None = None
    self._is_hub_chat: HubFn | None = None
    self._notify_admin: NotifyAdminFn | None = None
    self._clear_chat_state: ClearStateFn | None = None
    self._menu_keyboard: MenuKeyboardFn | None = None
    self._watcher_stop: threading.Event | None = None

  def configure(
    self,
    *,
    base_url: str,
    send_message: SendFn,
    delete_message: DeleteFn,
    edit_message: EditFn,
    is_hub_chat: HubFn,
    notify_admin: NotifyAdminFn,
    clear_chat_state: ClearStateFn,
    menu_keyboard: MenuKeyboardFn,
  ) -> None:
    self._base_url = base_url
    self._send_message = send_message
    self._delete_message = delete_message
    self._edit_message = edit_message
    self._is_hub_chat = is_hub_chat
    self._notify_admin = notify_admin
    self._clear_chat_state = clear_chat_state
    self._menu_keyboard = menu_keyboard
    self._load_message_logs()
    self.unlocked_until = self._load_unlocked_sessions()

  def auth_enabled(self) -> bool:
    return bool(os.getenv("BOT_ACCESS_PASSWORD", "").strip())

  def access_password(self) -> str:
    return os.getenv("BOT_ACCESS_PASSWORD", "").strip()

  def session_ttl_seconds(self) -> float | None:
    raw = os.getenv("BOT_ACCESS_SESSION_MINUTES", "30").strip() or "30"
    try:
      minutes = float(raw)
    except ValueError:
      minutes = 30.0
    if minutes <= 0:
      return None
    return minutes * 60.0

  def password_reply_markup(self) -> dict:
    return PASSWORD_FORCE_REPLY

  def start_watcher(self, user_names: dict[int | str, str]) -> None:
    if not self.auth_enabled() or self._watcher_stop is not None:
      return
    stop = threading.Event()

    def _loop() -> None:
      while not stop.wait(10.0):
        try:
          self.expire_due_sessions(user_names)
        except Exception as exc:
          print(f"[Telegram] Falha ao expirar sessão: {exc}", flush=True)

    threading.Thread(target=_loop, name="session-expiry", daemon=True).start()
    self._watcher_stop = stop

  def is_unlocked(self, chat_id: int | str) -> bool:
    if not self.auth_enabled():
      return True
    key = self._norm_chat_id(chat_id)
    expires = self.unlocked_until.get(key)
    if expires is None:
      return False
    if expires == float("inf"):
      return True
    if time.time() >= float(expires):
      self.unlocked_until.pop(key, None)
      self._persist_unlocked_sessions()
      return False
    return True

  def had_active_session(self, chat_id: int | str) -> bool:
    return self._norm_chat_id(chat_id) in self.unlocked_until

  def touch_session(self, chat_id: int | str) -> None:
    if not self.auth_enabled():
      return
    key = self._norm_chat_id(chat_id)
    if key not in self.unlocked_until:
      return
    ttl = self.session_ttl_seconds()
    self.unlocked_until[key] = float("inf") if ttl is None else time.time() + ttl
    self._persist_unlocked_sessions()

  def track_message(self, chat_id: int | str, message_id: int | None, *, durable: bool = False) -> None:
    if not self.auth_enabled() or not message_id:
      return
    if self._is_hub_chat and self._is_hub_chat(chat_id):
      return
    key = str(chat_id)
    mid = int(message_id)
    with self._message_log_lock:
      target = self._durable_message_log if durable else self._message_log
      log = target[key]
      if mid not in log:
        log.append(mid)
      if len(log) > MESSAGE_LOG_MAX:
        del log[: len(log) - MESSAGE_LOG_MAX]
      bounds = self._chat_msg_range.get(key)
      if not bounds:
        self._chat_msg_range[key] = [mid, mid]
      else:
        bounds[0] = min(bounds[0], mid)
        bounds[1] = max(bounds[1], mid)
    self._persist_message_logs()

  def handle_admin_password_callback(
    self,
    hub_chat_id: int | str,
    data: str,
    *,
    message_id: int | None,
  ) -> bool:
    raw = (data or "").strip()
    if not (raw.startswith("admin:pw:ok:") or raw.startswith("admin:pw:no:")):
      return False
    parts = raw.split(":")
    if len(parts) < 4:
      return True
    action = parts[2]
    item_id = parts[3]
    item = inbox.get_item(self.project_dir, item_id)
    if not item or item.get("type") != "password_help":
      self._send(hub_chat_id, "⚠️ Pedido não encontrado.")
      return True
    if item.get("status") != "open":
      self._send(hub_chat_id, "ℹ️ Este pedido já foi respondido.")
      return True

    user_chat = item.get("chat_id")
    who = (item.get("user_name") or "Usuário").strip() or "Usuário"
    if action == "ok":
      inbox.set_status(self.project_dir, item_id, "approved")
      state = {"step": "await_new", "item_id": item_id}
      self.password_reset_await[self._norm_chat_id(user_chat)] = state
      reset_set(self.project_dir, user_chat, {"step": "await_new", "item_id": item_id})
      self._send(
        user_chat,
        auth_messages.build_password_reset_approved(),
        reply_markup=self.password_reply_markup(),
        track=False,
      )
      body = f"{self._format_inbox_item(item)}\n\n✅ *Liberado* — {who} pode criar a senha nova agora."
      if message_id and self._edit_message:
        self._edit_message(hub_chat_id, message_id, body, parse_mode="Markdown")
      else:
        self._send(hub_chat_id, body)
      print(f"[Telegram] Admin liberou troca de senha para {who} ({user_chat}).", flush=True)
    else:
      inbox.set_status(self.project_dir, item_id, "denied")
      self.password_reset_await.pop(self._norm_chat_id(user_chat), None)
      reset_clear(self.project_dir, user_chat)
      self._send(user_chat, auth_messages.build_password_reset_denied(), track=False)
      body = f"{self._format_inbox_item(item)}\n\n❌ *Negado*."
      if message_id and self._edit_message:
        self._edit_message(hub_chat_id, message_id, body, parse_mode="Markdown")
      else:
        self._send(hub_chat_id, body)
      print(f"[Telegram] Admin negou troca de senha para {who} ({user_chat}).", flush=True)
    return True

  def handle_locked_message(
    self,
    chat_id: int | str,
    text: str,
    *,
    message_id: int | None,
    display_name: str,
    username: str = "",
    had_session: bool = False,
  ) -> bool:
    """True se consumiu a mensagem (não processar como comando de planilha)."""
    if had_session:
      self.end_session(chat_id, display_name=display_name, reason="ttl")
      return True

    if self._handle_password_reset_input(chat_id, text, message_id=message_id, display_name=display_name):
      return True

    if self._is_forgot_password_request(text):
      self._register_password_help(chat_id, display_name=display_name, username=username)
      return True

    if self._is_soft_auth_entry(text):
      self.prompt_password(chat_id, display_name)
      return True

    role = self._match_access_role(text, chat_id)
    if role:
      if message_id and self._delete_message:
        self._delete_message(chat_id, message_id)
      welcome = auth_messages.build_password_ok(display_name)
      self.finish_password_unlock(
        chat_id,
        display_name=display_name,
        welcome_text=welcome,
        password_message_id=message_id,
      )
      return True

    if message_id and self._delete_message:
      self._delete_message(chat_id, message_id)
    self._send(chat_id, auth_messages.build_password_wrong(), reply_markup=self.password_reply_markup())
    self.prompt_password(chat_id, display_name)
    return True

  def handle_unlocked_lock_command(self, chat_id: int | str, text: str, *, display_name: str) -> bool:
    if not self._is_lock_command(text):
      return False
    self.end_session(chat_id, display_name=display_name, reason="lock")
    return True

  def prompt_password(self, chat_id: int | str, display_name: str = "") -> None:
    key = str(self._norm_chat_id(chat_id))
    now = time.time()
    if now - self._last_password_prompt_at.get(key, 0.0) < 4.0:
      return
    self._last_password_prompt_at[key] = now
    self._send(
      chat_id,
      auth_messages.build_password_prompt(display_name),
      reply_markup=self.password_reply_markup(),
      track=False,
    )

  def finish_password_unlock(
    self,
    chat_id: int | str,
    *,
    display_name: str,
    welcome_text: str,
    password_message_id: int | None,
  ) -> None:
    key = str(chat_id)
    with self._message_log_lock:
      old_ids = list(self._message_log.get(key, ()))
      self._message_log[key].clear()
    self._persist_message_logs()
    self._unlock_chat(chat_id)
    if self._clear_chat_state:
      self._clear_chat_state(chat_id)
    menu = self._menu_keyboard() if self._menu_keyboard else None
    self._send(chat_id, welcome_text, reply_markup=menu)
    skip: set[int] = set()
    if password_message_id:
      skip.add(int(password_message_id))
      if self._delete_message:
        self._delete_message(chat_id, password_message_id)
    threading.Thread(
      target=lambda: self._wipe_ids(chat_id, old_ids, skip=skip),
      name=f"wipe-unlock-{chat_id}",
      daemon=True,
    ).start()

  def end_session(self, chat_id: int | str, *, display_name: str, reason: str = "lock") -> None:
    key = str(chat_id)
    with self._session_end_lock:
      if reason == "ttl":
        last = self._recent_ttl_ends.get(key)
        if last is not None and (time.time() - last) < 45:
          return
        self._recent_ttl_ends[key] = time.time()
      self._lock_chat(chat_id)
      if self._clear_chat_state:
        self._clear_chat_state(chat_id)
      with self._message_log_lock:
        old_ids = list(self._message_log.pop(key, ()))
        old_ids.extend(self._durable_message_log.pop(key, ()))
        self._chat_msg_range.pop(key, None)
      self._persist_message_logs()
      body = (
        auth_messages.build_session_expired_message()
        if reason == "ttl"
        else auth_messages.build_locked_message()
      )
      self._send(chat_id, body, reply_markup=self.password_reply_markup(), track=False)
      self.prompt_password(chat_id, display_name)
      wipe_ids = self._build_wipe_id_list(old_ids, aggressive=True)
      threading.Thread(
        target=lambda: self._wipe_ids(chat_id, wipe_ids),
        name=f"wipe-{reason}-{chat_id}",
        daemon=True,
      ).start()

  def expire_due_sessions(self, user_names: dict[int | str, str]) -> None:
    if not self.auth_enabled():
      return
    now = time.time()
    expired = [
      chat_id
      for chat_id, expires in list(self.unlocked_until.items())
      if expires != float("inf") and now >= float(expires)
    ]
    for chat_id in expired:
      display_name = user_names.get(chat_id, "") or "Usuário"
      self.end_session(chat_id, display_name=display_name, reason="ttl")

  def password_decide_keyboard(self, item_id: str) -> dict:
    return {
      "inline_keyboard": [
        [
          {"text": "✅ Liberar troca", "callback_data": f"admin:pw:ok:{item_id}"},
          {"text": "❌ Negar", "callback_data": f"admin:pw:no:{item_id}"},
        ]
      ]
    }

  def _register_password_help(self, chat_id: int | str, *, display_name: str, username: str) -> None:
    item = inbox.add_item(
      self.project_dir,
      item_type="password_help",
      chat_id=chat_id,
      user_name=display_name,
      username=username,
      text="Pediu ajuda: esqueci a senha de acesso.",
    )
    self._send(chat_id, auth_messages.build_password_help_received())
    notified = False
    if self._notify_admin:
      notified = self._notify_admin(
        "🔔 *Nova solicitação — troca de senha*\n\n" + self._format_inbox_item(item),
        self.password_decide_keyboard(str(item.get("id"))),
      )
    if not notified:
      self._send(
        chat_id,
        "⚠️ O admin ainda não configurou o grupo de alertas (`ADMIN_CHAT_ID`). "
        "Peça para adicionar o bot ao grupo *Robôs Sous Tec*.",
      )
    print(f"[Telegram] {display_name} pediu troca de senha (notificado={notified}).", flush=True)

  def _handle_password_reset_input(
    self,
    chat_id: int | str,
    text: str,
    *,
    message_id: int | None,
    display_name: str,
  ) -> bool:
    key = self._norm_chat_id(chat_id)
    state = self.password_reset_await.get(key) or reset_get(self.project_dir, chat_id)
    if not state:
      return False
    self.password_reset_await[key] = state
    cleaned = (text or "").strip()
    if not cleaned:
      return True
    if message_id and self._delete_message:
      self._delete_message(chat_id, message_id)
    step = state.get("step")
    if step == "await_new":
      if len(cleaned) < 4:
        self._send(
          chat_id,
          auth_messages.build_password_reset_too_short(),
          reply_markup=self.password_reply_markup(),
        )
        return True
      if self._secure_password_equals(cleaned, self.access_password()):
        self._send(
          chat_id,
          "⚠️ Escolha uma senha diferente da senha padrão de acesso.",
          reply_markup=self.password_reply_markup(),
        )
        return True
      new_state = {**state, "step": "await_confirm", "first": cleaned}
      self.password_reset_await[key] = new_state
      reset_set(self.project_dir, chat_id, {"step": "await_confirm", "item_id": state.get("item_id")})
      self._send(
        chat_id,
        auth_messages.build_password_reset_prompt_confirm(),
        reply_markup=self.password_reply_markup(),
      )
      return True
    if step == "await_confirm":
      first = str(state.get("first") or "")
      if not first or cleaned != first:
        self.password_reset_await[key] = {"step": "await_new", "item_id": state.get("item_id")}
        reset_set(self.project_dir, chat_id, {"step": "await_new", "item_id": state.get("item_id")})
        self._send(
          chat_id,
          auth_messages.build_password_reset_mismatch(),
          reply_markup=self.password_reply_markup(),
        )
        return True
      user_set_password(self.project_dir, chat_id, cleaned)
      self.password_reset_await.pop(key, None)
      reset_clear(self.project_dir, chat_id)
      self._unlock_chat(chat_id)
      menu = self._menu_keyboard() if self._menu_keyboard else None
      self._send(
        chat_id,
        auth_messages.build_password_changed_ok(display_name),
        reply_markup=menu,
      )
      print(f"[Telegram] {display_name} definiu senha pessoal após aprovação.", flush=True)
      return True
    return False

  def _send(
    self,
    chat_id: int | str,
    text: str,
    *,
    reply_markup: dict | None = None,
    track: bool = True,
    parse_mode: str = "Markdown",
  ) -> None:
    if not self._send_message:
      return
    self._send_message(
      chat_id,
      text,
      parse_mode=parse_mode,
      reply_markup=reply_markup,
      track=track,
    )

  def _format_inbox_item(self, item: dict[str, Any]) -> str:
    who = (item.get("user_name") or "Usuário").strip() or "Usuário"
    username = (item.get("username") or "").strip()
    user_line = f"*{who}*"
    if username:
      user_line += f" (@{username.lstrip('@')})"
    chat_id = item.get("chat_id")
    text = (item.get("text") or "").strip()
    lines = [user_line, f"Chat ID: `{chat_id}`"]
    if text:
      lines.append(f"_{text}_")
    return "\n".join(lines)

  def _unlock_chat(self, chat_id: int | str) -> None:
    ttl = self.session_ttl_seconds()
    key = self._norm_chat_id(chat_id)
    self.unlocked_until[key] = float("inf") if ttl is None else time.time() + ttl
    self._persist_unlocked_sessions()

  def _lock_chat(self, chat_id: int | str) -> None:
    self.unlocked_until.pop(self._norm_chat_id(chat_id), None)
    self._persist_unlocked_sessions()

  def _load_unlocked_sessions(self) -> dict[int | str, float]:
    if not self._sessions_file.is_file():
      return {}
    try:
      raw = json.loads(self._sessions_file.read_text(encoding="utf-8"))
    except Exception:
      return {}
    if not isinstance(raw, dict):
      return {}
    now = time.time()
    restored: dict[int | str, float] = {}
    for key, value in raw.items():
      chat_id = self._norm_chat_id(key)
      expires: float | None = None
      if isinstance(value, dict):
        try:
          expires = float(value.get("expires"))
        except (TypeError, ValueError):
          continue
      else:
        try:
          expires = float(value)
        except (TypeError, ValueError):
          continue
      if expires is None:
        continue
      if expires == float("inf") or expires > now:
        restored[chat_id] = expires
    return restored

  def _persist_unlocked_sessions(self) -> None:
    now = time.time()
    payload: dict[str, dict[str, float]] = {}
    for chat_id, expires in self.unlocked_until.items():
      try:
        exp = float(expires)
      except (TypeError, ValueError):
        continue
      if exp != float("inf") and exp <= now:
        continue
      payload[str(self._norm_chat_id(chat_id))] = {"expires": exp}
    try:
      self._sessions_file.parent.mkdir(parents=True, exist_ok=True)
      self._sessions_file.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:
      print(f"[Telegram] Falha ao salvar sessões: {exc}", flush=True)

  def _message_log_path(self) -> Path:
    return runtime_file(self.project_dir, "chat_message_ids.json")

  def _load_message_logs(self) -> None:
    path = self._message_log_path()
    if not path.is_file():
      return
    try:
      raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
      return
    if not isinstance(raw, dict):
      return
    with self._message_log_lock:
      for key, ids in (raw.get("session") or {}).items():
        if isinstance(ids, list):
          self._message_log[str(key)] = [int(x) for x in ids if str(x).isdigit()]
      for key, ids in (raw.get("durable") or {}).items():
        if isinstance(ids, list):
          self._durable_message_log[str(key)] = [int(x) for x in ids if str(x).isdigit()]
      for key, bounds in (raw.get("ranges") or {}).items():
        if isinstance(bounds, list) and len(bounds) >= 2:
          self._chat_msg_range[str(key)] = [int(bounds[0]), int(bounds[1])]

  def _persist_message_logs(self) -> None:
    try:
      with self._message_log_lock:
        payload = {
          "session": {k: list(v) for k, v in self._message_log.items() if v},
          "durable": {k: list(v) for k, v in self._durable_message_log.items() if v},
          "ranges": {k: list(v) for k, v in self._chat_msg_range.items() if v},
        }
      self._message_log_path().write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
      )
    except Exception:
      pass

  def _wipe_ids(self, chat_id: int | str, message_ids: list[int], *, skip: set[int] | None = None) -> int:
    skip = skip or set()
    ids = [int(mid) for mid in message_ids if mid and int(mid) not in skip]
    if not ids:
      return 0
    wiped = 0
    ids.sort(reverse=True)
    for i in range(0, len(ids), WIPE_BATCH):
      chunk = ids[i : i + WIPE_BATCH]
      if self._delete_messages_batch(chat_id, chunk):
        wiped += len(chunk)
      elif self._delete_message:
        for mid in chunk:
          if self._delete_message(chat_id, mid):
            wiped += 1
      if i + WIPE_BATCH < len(ids):
        time.sleep(0.08)
    self._persist_message_logs()
    return wiped

  def _delete_messages_batch(self, chat_id: int | str, message_ids: list[int]) -> bool:
    if not message_ids or not self._base_url:
      return False
    try:
      r = requests.post(
        f"{self._base_url}/deleteMessages",
        json={"chat_id": str(chat_id), "message_ids": message_ids[:100]},
        timeout=20,
      )
      return r.status_code == 200 and bool(r.json().get("ok"))
    except Exception:
      return False

  def _build_wipe_id_list(self, message_ids: list[int], *, aggressive: bool = False) -> list[int]:
    seen: set[int] = set()
    unique: list[int] = []
    for mid in message_ids:
      try:
        mid_i = int(mid)
      except (TypeError, ValueError):
        continue
      if mid_i <= 0 or mid_i in seen:
        continue
      seen.add(mid_i)
      unique.append(mid_i)
    if not unique:
      return unique
    hi = max(unique)
    start = max(1, hi - (WIPE_LOOKBACK if aggressive else 80))
    return list(range(start, hi + 1))

  def _secure_password_equals(self, attempt: str, expected: str) -> bool:
    if not expected:
      return False
    left = (attempt or "").strip().encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
      return False
    return hmac.compare_digest(left, right)

  def _match_access_role(self, text: str, chat_id: int | str | None) -> str | None:
    cleaned = (text or "").strip()
    if chat_id is not None and user_verify_password(self.project_dir, chat_id, cleaned):
      return "user"
    if self._secure_password_equals(cleaned, self.access_password()):
      return "user"
    return None

  def _is_lock_command(self, text: str) -> bool:
    cleaned = (text or "").strip()
    if cleaned == MENU_ENCERRAR_SESSAO:
      return True
    return self._normalize_reply(cleaned) in LOCK_WORDS

  def _is_forgot_password_request(self, text: str) -> bool:
    return self._normalize_reply(text or "") in FORGOT_PASSWORD_PHRASES

  def _is_soft_auth_entry(self, text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
      return True
    lower = cleaned.lower()
    if lower in {"/start", "/help", "ajuda", "help", "oi", "olá", "ola", "/chatid", "/id"}:
      return True
    if self._is_forgot_password_request(cleaned):
      return True
    for ch in ("📄", "📊", "📋", "✏️", "🔄", "❓", "🔒"):
      cleaned_btn = cleaned.lower().replace(ch, "").strip()
      if cleaned_btn in {
        "prévia",
        "previa",
        "resumo",
        "relatório pdf",
        "relatorio pdf",
        "corrigir",
        "ajuda",
        "nova conversa",
        "encerrar sessão",
        "encerrar sessao",
      }:
        return True
    return False

  @staticmethod
  def _normalize_reply(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

  @staticmethod
  def _norm_chat_id(chat_id: int | str) -> int | str:
    try:
      return int(chat_id)
    except (TypeError, ValueError):
      return chat_id
