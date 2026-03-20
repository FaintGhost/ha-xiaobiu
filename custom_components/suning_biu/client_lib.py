from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


class SuningDependencyError(RuntimeError):
  pass


@dataclass(frozen=True, slots=True)
class SuningClientLib:
  AirConditionerStatus: type[Any]
  AuthenticationError: type[Exception]
  CaptchaRequiredError: type[Exception]
  CaptchaSolution: type[Any]
  FamilyInfo: type[Any]
  LocalCaptchaBridge: type[Any]
  SuningError: type[Exception]
  SuningSmartHomeClient: type[Any]


@lru_cache(maxsize=1)
def _load_client_lib() -> SuningClientLib:
  from suning_biu_ha import (
    AirConditionerStatus,
    AuthenticationError,
    CaptchaRequiredError,
    CaptchaSolution,
    FamilyInfo,
    SuningError,
    SuningSmartHomeClient,
  )
  from suning_biu_ha.captcha_bridge import LocalCaptchaBridge

  return SuningClientLib(
    AirConditionerStatus=AirConditionerStatus,
    AuthenticationError=AuthenticationError,
    CaptchaRequiredError=CaptchaRequiredError,
    CaptchaSolution=CaptchaSolution,
    FamilyInfo=FamilyInfo,
    LocalCaptchaBridge=LocalCaptchaBridge,
    SuningError=SuningError,
    SuningSmartHomeClient=SuningSmartHomeClient,
  )


def load_client_lib() -> SuningClientLib:
  try:
    return _load_client_lib()
  except Exception as error:
    _LOGGER.exception("Failed to import suning_biu_ha runtime dependency")
    raise SuningDependencyError("suning_biu_ha runtime dependency is unavailable") from error