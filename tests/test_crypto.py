from __future__ import annotations

import base64

from xiaobiu.client import DEFAULT_LOGIN_PAGE_CONFIG
from xiaobiu.crypto import (
  SuAESCipher,
  decode_suning_base64,
  encode_suning_base64,
  rsa_encrypt_base64,
)


def test_suaes_roundtrip() -> None:
  cipher = SuAESCipher()
  payload = '{"sceneId":"PASSPORT","phone":"13800000000"}'
  encrypted = cipher.encrypt(payload)
  assert cipher.decrypt(encrypted) == payload


def test_custom_base64_roundtrip() -> None:
  raw = b"suning"
  encoded = encode_suning_base64(raw)
  assert decode_suning_base64(encoded) == raw


def test_rsa_encrypt_output_matches_1024_bit_key_size() -> None:
  encrypted = rsa_encrypt_base64("13800000000", DEFAULT_LOGIN_PAGE_CONFIG.check_account_key)
  assert len(base64.b64decode(encrypted)) == 128
