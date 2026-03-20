from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SUNING_AES_KEY = b"www.cnsuning.com"
SUNING_AES_IV = b"moc.gninusnc.www"
STANDARD_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
SUNING_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()*"
STANDARD_TO_SUNING_BASE64 = str.maketrans(
  STANDARD_BASE64_ALPHABET,
  SUNING_BASE64_ALPHABET,
)
SUNING_TO_STANDARD_BASE64 = str.maketrans(
  SUNING_BASE64_ALPHABET,
  STANDARD_BASE64_ALPHABET,
)


def encode_suning_base64(raw: bytes) -> str:
  return base64.b64encode(raw).decode("ascii").translate(STANDARD_TO_SUNING_BASE64)


def decode_suning_base64(encoded: str) -> bytes:
  return base64.b64decode(encoded.translate(SUNING_TO_STANDARD_BASE64))


class SuAESCipher:
  def __init__(self, key: bytes = SUNING_AES_KEY, iv: bytes = SUNING_AES_IV) -> None:
    self._key = key
    self._iv = iv

  def encrypt(self, plaintext: str) -> str:
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(self._key), modes.CBC(self._iv))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return encode_suning_base64(encrypted)

  def decrypt(self, ciphertext: str) -> str:
    cipher = Cipher(algorithms.AES(self._key), modes.CBC(self._iv))
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(decode_suning_base64(ciphertext)) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(decrypted) + unpadder.finalize()
    return plaintext.decode("utf-8")


@lru_cache(maxsize=8)
def _load_public_key(public_key_base64: str):
  key_bytes = base64.b64decode(public_key_base64)
  return serialization.load_der_public_key(key_bytes)


def rsa_encrypt_base64(plaintext: str, public_key_base64: str) -> str:
  public_key = _load_public_key(public_key_base64)
  encrypted = public_key.encrypt(
    plaintext.encode("utf-8"),
    asymmetric_padding.PKCS1v15(),
  )
  return base64.b64encode(encrypted).decode("ascii")
