# suning-biu-ha

Python client and Home Assistant custom integration for Suning SMS login and smart-home session reuse.

## Current status

- Normal CLI usage and the Home Assistant integration no longer require a HAR file.
- Family and device APIs are signed at runtime using the Android `gsSign` algorithm.
- SMS login supports Suning's current mobile login parameters (`PASSPORT_XIAOBIU` / `MOBILE`).
- When Suning requires IAR verification, the CLI local bridge page and the Home Assistant external-step page both collect the browser-generated `detect` and `dfpToken` values before retrying `sendCode.do`.
- The same runtime is vendored into the Home Assistant integration under `custom_components/suning_biu/suning_biu_ha`.

## Codebase layout

- `src/suning_biu_ha/`
  - Core runtime: SMS login, session persistence, service bootstrap, smart-home API signing, CLI entrypoint
- `custom_components/suning_biu/`
  - Home Assistant integration: config flow, coordinator, climate entities, vendored runtime
- `tests/`
  - Runtime, captcha bridge, CLI, and Home Assistant integration tests
- `tasks/`
  - Working notes and project lessons captured during protocol reverse engineering

## Home Assistant custom component

This repository includes a Home Assistant custom integration at `custom_components/suning_biu`.

- Home Assistant version target: `2026.3.2`
- Project Python target: `3.14`
- Custom integration version: `0.1.5`
- The integration vendors its own runtime and does not depend on a private GitHub package URL in `manifest.json`
- Setup path: **Settings → Devices & Services → Add Integration → Suning Biu**
- Config flow inputs:
  - phone number
  - international code
- Login flow:
  - the integration sends the SMS code through Suning's current login flow
  - if Suning requires IAR verification, the config flow uses a Home Assistant hosted external step instead of a `127.0.0.1` bridge URL
  - the verification page computes the current browser risk context and posts it back together with the IAR token
  - after the verification page submits successfully, Home Assistant resumes the flow automatically
  - after SMS login succeeds, the config flow lets you choose a family
  - after the integration is added, you can open the entry menu and use **Reconfigure** to refresh the family list and switch to a different family
  - the integration signs the smart-home app family/device requests at runtime and no longer asks for a HAR file
- Entity model:
  - devices are refreshed through a coordinator with periodic keep-alive
  - air conditioners in the selected family are exposed as `climate` entities
  - offline devices are created in Home Assistant as unavailable climate entities

## Verified capabilities

- Parse the Suning login page at runtime to extract the current RSA public keys and flow constants.
- Reproduce `needVerifyCode.do` and `sendCode.do` using Suning's `SuAES` scheme.
- Reproduce `ids/smartLogin/sms` using the RSA-encrypted phone number flow.
- Automatically recover browser-side `detect` / `dfpToken` during IAR verification and reuse them for the SMS send/login chain.
- Persist cookies and auth state into a local JSON state file.
- Re-bootstrap `shcss` and `itapig` service sessions after login.
- Reverse-engineer `gsSign` and sign smart-home app family/device requests at runtime.
- Verify the session by calling member info, family list, and device list endpoints.
- Normalize AC device payloads into a more stable status model and provide a Home Assistant climate preview.

## Important limits

- When Suning returns `isIarVerifyCode`, the CLI still relies on a local bridge page. The Home Assistant integration now serves its own verification page from the HA host, but non-IAR captcha types still need manual handling.
- Other captcha types are not yet fully bridged. If Suning returns a non-IAR captcha, a token still needs to be provided manually.
- `--detect` and `--dfp-token` are still accepted as debugging overrides, but the IAR path no longer needs them in the normal flow.
- `--har-file` is still accepted only as a debug fallback for protocol research; the Home Assistant integration and normal CLI family/device queries no longer depend on HAR input.
- The vendored runtime and `src/` runtime are duplicated on purpose for Home Assistant packaging. If login or protocol behavior changes again, both copies must stay in sync.
- Session files contain cookies and login state. They are local secrets and should not be committed.

## Install

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv sync --dev
```

## CLI

Interactive login flow:

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run main.py login \
  --phone 13800000000 \
  --state-file .suning-session.json
```

If the server asks for IAR puzzle verification, the terminal will print a local link such as:

```bash
http://127.0.0.1:43127/
```

Open that link in a browser, finish the puzzle, then return to the terminal and enter the SMS code when prompted.

Send an SMS code only:

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run main.py send-sms \
  --phone 13800000000 \
  --state-file .suning-session.json
```

Check whether the session is still valid:

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run main.py check \
  --state-file .suning-session.json
```

List families and devices:

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run main.py families \
  --state-file .suning-session.json

env UV_CACHE_DIR=/tmp/uv-cache uv run main.py devices \
  --family-id 37790 \
  --state-file .suning-session.json

env UV_CACHE_DIR=/tmp/uv-cache uv run main.py device-status \
  --family-id 37790 \
  --device-id 000165f9b029afa2e5d8 \
  --state-file .suning-session.json

env UV_CACHE_DIR=/tmp/uv-cache uv run main.py device-status \
  --family-id 37790 \
  --raw
```

## Home Assistant test checklist

1. Copy `custom_components/suning_biu` into your Home Assistant config directory.
2. Restart Home Assistant on Python `3.14` / Home Assistant `2026.3.2`.
3. Add the `Suning Biu` integration from **Settings → Devices & Services**.
4. Enter the phone number and international code.
5. If the flow enters the IAR step, open the Home Assistant provided verification page in the same browser, finish the puzzle, and wait for the flow to resume automatically.
6. Enter the SMS code, select the family, and confirm that `climate` entities are created.
7. If the login succeeds but devices do not appear, verify the selected family actually contains supported air conditioners.
8. To switch the imported family later, open the integration entry menu in Home Assistant and use **Reconfigure**. If the saved session has expired, the flow will ask for a fresh SMS code before showing the family list again.

## Library usage

```python
from suning_biu_ha import CaptchaRequiredError, SuningSmartHomeClient

client = SuningSmartHomeClient(state_path=".suning-session.json")

try:
  client.send_sms_code("13800000000")
except CaptchaRequiredError as error:
  print(error.risk_type, error.sms_ticket)

client.login_with_sms_code(phone_number="13800000000", sms_code="123456")
print(client.list_families())
```
