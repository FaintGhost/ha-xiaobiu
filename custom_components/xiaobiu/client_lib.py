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
  DeviceCapabilities: type[Any]
  FamilyInfo: type[Any]
  FanSpeed: type[Any]
  HvacAction: type[Any]
  HvacMode: type[Any]
  LocalCaptchaBridge: type[Any]
  PresetMode: type[Any]
  SmsRateLimitedError: type[Exception]
  SuningError: type[Exception]
  SuningSmartHomeClient: type[Any]
  SwingMode: type[Any]


@lru_cache(maxsize=1)
def _load_client_lib() -> SuningClientLib:
  from xiaobiu import (
    AirConditionerStatus,
    AuthenticationError,
    CaptchaRequiredError,
    CaptchaSolution,
    FamilyInfo,
    FanSpeed,
    HvacAction,
    HvacMode,
    PresetMode,
    SmsRateLimitedError,
    SuningError,
    SuningSmartHomeClient,
    SwingMode,
  )
  from xiaobiu.captcha_bridge import LocalCaptchaBridge
  from xiaobiu.models import DeviceCapabilities

  return SuningClientLib(
    AirConditionerStatus=AirConditionerStatus,
    AuthenticationError=AuthenticationError,
    CaptchaRequiredError=CaptchaRequiredError,
    CaptchaSolution=CaptchaSolution,
    DeviceCapabilities=DeviceCapabilities,
    FamilyInfo=FamilyInfo,
    FanSpeed=FanSpeed,
    HvacAction=HvacAction,
    HvacMode=HvacMode,
    LocalCaptchaBridge=LocalCaptchaBridge,
    PresetMode=PresetMode,
    SmsRateLimitedError=SmsRateLimitedError,
    SuningError=SuningError,
    SuningSmartHomeClient=SuningSmartHomeClient,
    SwingMode=SwingMode,
  )


def load_client_lib() -> SuningClientLib:
  try:
    return _load_client_lib()
  except Exception as error:
    _LOGGER.exception("Failed to import xiaobiu runtime dependency")
    raise SuningDependencyError("xiaobiu runtime dependency is unavailable") from error
