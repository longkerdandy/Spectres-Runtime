# Mi Fitness Cloud API — Project Research Reference

Status: static and dynamic research through v0.1.2, reviewed 2026-10-31. This
document covers only the non-public upstream APIs needed for own-account
authentication and cloud reads of smartwatch and body-composition scale data.
It is not an official Xiaomi contract, a stability guarantee, or the built-in
Extension's public FastAPI interface.

Official-app results apply specifically to the unmodified Mi Fitness APK 3.59.2,
build 359002. Standalone harness results are identified separately. Neither
establishes compatibility with other APK versions or real watch/scale
measurements.

## 1. Evidence and Scope

Evidence labels used below:

- **Cross-checked static**: the official APK 3.59.2 and at least one reviewed
  open-source implementation support the interface or behavior.
- **APK static**: the current official APK supports it, but the reviewed
  open-source projects do not provide equivalent current call-chain evidence.
- **Upstream runtime note**: an open-source project reports a live behavior.
  This is useful implementation guidance, not independent verification by this
  project.
- **Dynamic, APK 3.59.2**: verified using the unmodified official APK 3.59.2,
  build 359002.
- **Dynamic, standalone 2026-10-31**: verified by the disposable local harness
  without using the official app's stored session. Raw credentials and health
  values are excluded from this document.

Reviewed sources:

- `M`: Jenwein/mifit, commit
  [`00b8e157`](https://github.com/Jenwein/mifit/tree/00b8e15711b027057d82c436c230da55849ee34d),
  MIT.
- `C`: HUAYUE1024/mi-fitness-mcp-cn, commit
  [`1767b492`](https://github.com/HUAYUE1024/mi-fitness-mcp-cn/tree/1767b4921ad94e38a68ac77cbb0bdf809a92864d),
  MIT.
- `S`: AlexxIT/SmartScaleConnect, commit
  [`a9e5c04f`](https://github.com/AlexxIT/SmartScaleConnect/tree/a9e5c04f1079b65d456c8a5fd296775a1ef29e8f),
  MIT.
- `A`: official Mi Fitness `com.mi.health` 3.59.2, build 359002, decompiled
  under `research-local/jadx/3.59.2_20261023185032/`.

`SmartScaleConnect` is useful for its account login, encrypted transport, weight
pagination, body-composition fields, and scale attribution clues. It is not a
smartwatch reference. Its older alternative scale endpoints are not selected
when the current APK provides a clearer path.

### Dynamic validation summary — APK 3.59.2, build 359002

On 2026-10-31, the unmodified APK ran on the Android 15 API 35
`mi-health-google-apis` emulator with ARM translation. mitmproxy 12.3.1
inspected HTTPS traffic without a certificate-pinning bypass. The account used
the China region. Raw flows remain only in the Git-ignored research directory.

The official app completed phone/SMS authentication through
`/pass/sendServiceLoginTicket`, `/pass/phoneInfo`, and
`/pass/serviceLoginTicketAuth`. The successful result had `code: 0` and
`securityStatus: 0` and contained `userId`, `cUserId`, `passToken`, `ssecurity`,
`nonce`, and `location`. An earlier `/pass/serviceLogin` attempt returned
`70016` before ticket authentication; this was part of the interactive login,
not an observed health-session renewal failure.

The resulting health STS request went to
`https://sts-hlth.io.mi.com/healthapp/sts`. Its `clientSign` exactly matched the
algorithm in Section 3.5, and the response set `userId`, `cUserId`, and
`serviceToken` cookies. No `miothealth` renewal with `passToken` occurred in
this official-app session. Successful renewals observed for other Xiaomi
service IDs are not evidence for the health-service renewal path.

The following selected interfaces returned HTTP 200, matched the documented
request-signature algorithm, and decrypted to business `code: 0` using the
captured session's `ssecurity`:

- `GET /healthapp/user/get_miot_user_profile`, including its special signature
  path.
- `GET /app/v1/data/get_aggregated_fitness_data_by_time`.
- `GET /app/v1/data/get_fitness_data_by_time`.
- `GET /app/v1/data/get_sport_records_by_time`.

The decrypted pagination envelopes had the documented `data_list` or
`sport_records`, `has_more`, and `next_key` fields. The observed record lists
were empty, so this experiment validates authentication, transport, and envelope
shape, not measurement semantics or device support.

The official password route used uppercase MD5 password encoding and reached
`code: 0` with `securityStatus: 32`. It required phone security confirmation
before session establishment. The security branch's later managed STS signature
did not match the formula using the preceding `/serviceLoginAuth2/end` header
material; that specific transition remains unresolved.

### Dynamic validation summary — standalone harness, 2026-10-31

One independent password attempt returned `code: 0`, `securityStatus: 16`, and
a `notificationUrl`, but no `location` or session fields. Unlike the official
`securityStatus: 32` result, this does not establish password acceptance. The
harness stopped without retrying and selected QR fallback.

A complete QR login then succeeded with owner approval: the poll returned HTTP
200, `code: 0`, and `securityStatus: 0`; the STS exchange returned
`serviceToken`; Profile and daily-steps aggregation both decrypted to business
`code: 0`. This was an independent project-controlled flow using its own
research `deviceId`, not the official app's session.

One `sid=miothealth` renewal succeeded without a password. `passToken` remained
unchanged, while `serviceToken` and `ssecurity` changed. Post-renewal Profile
and daily aggregation returned business `code: 0`. The replaced service session
also remained accepted in one immediate control read, demonstrating short-term
coexistence but not a token lifetime.

One deliberately invalid health signature returned HTTP 401 with plaintext
JSON containing business `code: 0`; no renewal was attempted. Thus HTTP 401 and
business `code: 0` do not by themselves prove session expiration.

The initial implementation API set is:

| Purpose | API |
|---|---|
| Start QR authentication | `GET /longPolling/loginUrl` |
| Wait for QR approval | `GET` the server-provided `lp` URL |
| Exchange login for a service session | `GET` the login-result `location` URL |
| Renew a service session | `GET /pass/serviceLogin`, then the new `location` URL |
| Read account/profile context | `GET /healthapp/user/get_miot_user_profile` |
| Read daily watch summaries | `GET /app/v1/data/get_aggregated_fitness_data_by_time` |
| Read raw watch metrics and weight | `GET /app/v1/data/get_fitness_data_by_time` |
| Read workout summaries | `GET /app/v1/data/get_sport_records_by_time` |
| Read scale users and attributed records | `POST /app/v1/eco/api_proxy` with two documented `eco_api` values |

**Initial scope decision**: support only QR login and automatic `passToken`
renewal. Reuse the existing service session first, renew when needed, and
request new QR approval when renewal is unavailable or fails. Password
automation, password recovery, and standalone SMS login are outside the initial
implementation; Sections 3.1–3.2 retain password observations only as
historical research evidence. No account password should be collected or
stored. See the
[authentication implementation contract](mi-fitness-authentication-contract.md).
Workout-detail/FDS downloads, GPS, writes, deletes, relative sharing, and
watermark APIs remain excluded.

## 2. Shared Authentication and Transport

### 2.1 Service and region

Use Xiaomi account service ID `miothealth`. **Cross-checked static**: `M
src/mifit/region.py`; `A sources/com/xiaomi/fitness/account/SIDs.java`.

Health hosts are regional:

```text
cn: https://hlth.io.mi.com
other region R: https://R.hlth.io.mi.com
```

Observed region codes are `cn`, `de`, `i2`, `ru`, `sg`, and `us`. Send
`region_tag: R` on health requests. Country-to-region mappings are in the APK's
`assets/server_config/servers.json`; do not silently default an unknown account
to `cn`. **Cross-checked static**: `M transport.py`, `C` adapter, `S client.go`;
`A RegionUrlSwitcherImpl.java`. **Dynamic, APK 3.59.2**: authenticated China
region health requests carried the `region_tag: cn` header.

### 2.2 Session material

The authentication flow produces or uses:

- `userId` and `cUserId`: account identity values; treat as personal data.
- `passToken`: long-lived account credential used for renewal; highly sensitive.
- `serviceToken`: health-service credential sent as a cookie.
- `ssecurity`: secret used to derive health-request encryption/signing keys.
- `deviceId`: stable identifier reused across QR approval and renewal.

Never log these values, the dynamic `lp` or `location` URLs, complete cookies,
or authorization responses. Persistence and rotation storage remain project
design decisions.

Health requests carry `serviceToken` and `cUserId` cookies; `locale` is optional.
They do not send `passToken`. **Cross-checked static**: `M transport.py`; `A
CookieSingleModule.java` and `VerifyToken.java`. **Dynamic, APK 3.59.2**: the
observed health requests sent `serviceToken`, `cUserId`, and `locale`, but not
`userId`, although STS had set it. Thus `userId` was not required for the
observed calls; this does not establish that every regional or future endpoint
can omit it.

### 2.3 Signed and encrypted health requests

The selected health APIs use the encrypted-response path. `M` uses signed GET
requests; `C` and `S` demonstrate the corresponding POST form transport. The
APK supports both. **Cross-checked static**: `M crypto.py`, `C` adapter, `S
auth.go`; `A CloudInterceptor.java`, `zi4.java`, `di4.java`, `xj4.java`, and
`o0l.java`.

For each request:

1. Create a 12-byte nonce: eight random bytes followed by a big-endian 32-bit
   timestamp measured in whole minutes since the Unix epoch. Base64 encoding
   produces `_nonce`.
2. Compute `signedNonce = SHA256(base64Decode(ssecurity) || nonceBytes)`.
3. Put business JSON in the `data` parameter. Compact JSON is used by the
   reference implementations.
4. Build `rc4_hash__` as the SHA-1 signature over the plaintext parameters:
   `METHOD & signature-path & sorted key=value entries & base64(signedNonce)`.
5. Encrypt parameter values, including `rc4_hash__`, in sorted-key order with
   one continuous RC4 stream keyed by `signedNonce`. Discard the first 1024
   keystream bytes and Base64-encode each encrypted value.
6. Build `signature` the same way over the encrypted parameters, then append
   the unencrypted `_nonce`.
7. Base64-decode and decrypt the response with a fresh RC4 stream using the same
   nonce and the 1024-byte discard. Parse the resulting JSON envelope.

The signature uses plain SHA-1, not HMAC-SHA-256. The APK has a different HMAC
path for requests without encrypted responses; it is not the path selected
here.

For GET APIs, `data` and the signing fields are query parameters. For the scale
proxy, they are `application/x-www-form-urlencoded` POST fields. Successful
business responses normally have `code: 0`; the data is under `result`.

HTTP 401 can mean either an expired/revoked session or a rejected signature.
Do not repeatedly renew on every 401. **Dynamic, standalone 2026-10-31**: one
Profile request with a deliberately invalid signature returned HTTP 401 and a
plaintext JSON body containing only `code` and `message`, with business
`code: 0`; no renewal was attempted. A client must not interpret that business
code as a successful read or proof of expiry. The final application retry policy
is out of scope. **Static + upstream runtime note**: `M transport.py`; `A
VerifyToken.java`.

### 2.4 Common time and record semantics

- Health time-window fields use Unix **seconds**, not milliseconds.
- Raw rows have `zone_offset` in seconds and may have an IANA `zone_name`.
- Nested sport/sleep `timezone` values use 15-minute units.
- `next_key` is an opaque page cursor, not a durable synchronization cursor.
- Preserve source `sid`, deletion flags, and raw payloads until stable record
  keys and deduplication rules are designed.

## 3. Authentication APIs

Account responses may begin with `&&&START&&&`; strip that prefix before JSON
parsing. A nonzero `securityStatus` requires user security confirmation, not an
unattended retry.

### 3.1 Authenticate with a password (historical research)

**Out of initial implementation scope**: this subsection and Section 3.2 record
what was observed before the owner selected QR-only authentication. They are
not requirements for the initial client, and no further password-login
validation is required by v0.1.2.

**APK static**: `PasswordLoginFragment` → `LoginAndRegisterController` →
`PhoneLoginController` → `XMPassport.loginByPassword(PasswordLoginParams)`.

First obtain the service challenge:

```http
GET https://account.xiaomi.com/pass/serviceLogin?sid=miothealth&_json=true
Cookie: deviceId=<research deviceId>
```

Then submit the returned `_sign`, `qs`, `callback`, and `sid`:

```http
POST https://account.xiaomi.com/pass/serviceLoginAuth2
Cookie: deviceId=<same deviceId>
Content-Type: application/x-www-form-urlencoded

_json=true&_locale=<locale>&_sign=<...>&callback=<...>&hash=<...>&qs=<...>&sid=miothealth&user=<...>
```

**Dynamic, APK 3.59.2**: the initial service challenge returned `70016` and
provided `_sign`, `qs`, `callback`, `serviceParam`, and `sid`. The password
`hash` was 32-character uppercase hexadecimal, consistent with uppercase MD5.
No EUI header was present; the EUI/RSA/AES path was not used in this capture.
The response was HTTP 200 with `code: 0`, `securityStatus: 32`, and a
`notificationUrl`, but no `location`.

**Dynamic, standalone 2026-10-31**: the same request shape returned `code: 0`,
`securityStatus: 16`, and a `notificationUrl`, but no `location`, `userId`,
`cUserId`, `passToken`, `ssecurity`, or `nonce`. This does not establish that
the password was accepted. The one-attempt probe stopped without saving a
session or making STS/health requests. Fully non-interactive password login is
therefore unverified for the current account.

### 3.2 Handle password security confirmation

**Dynamic, APK 3.59.2**: after `securityStatus: 32`, owner interaction continued
through `/pass2/userinfo/start`, `/pass2/confirmPhone`,
`/pass2/userinfo/check`, and `/pass/serviceLoginAuth2/end`. The `/end` response
was HTTP 302, set `passToken`, `userId`, and `cUserId`, supplied `nonce` and
`ssecurity` in `Extension-Pragma`, and redirected to the health STS endpoint.

A later managed STS request included `clientSign`, but it did not match the
formula in Section 3.5 using the `/end` header's nonce and `ssecurity`; its
query nonce also differed. Do not claim that this security-branch transition
has been reproduced. Select QR fallback rather than repeatedly submitting the
password or automating around the account challenge.

### 3.3 Create a QR login challenge

**Cross-checked static**: `M auth/qr.py::request_qr_login`; `A
XMPassport.getQRLoginUrl`.

```http
GET https://account.xiaomi.com/longPolling/loginUrl?sid=miothealth&_json=true
```

There is no `/pass` prefix on this endpoint.

Send the same generated `deviceId` cookie used again during polling and renewal.
`M` uses 16 uppercase hexadecimal characters; the APK also supports its own
managed device ID.

Consumed response fields:

| Field | Meaning |
|---|---|
| `code` | Must be `0`. |
| `loginUrl` | Official page to present to the user. |
| `qr` | QR payload to present; do not treat it as a public URL. |
| `lp` | Session-bound long-polling URL for the next step; sensitive. |
| `timeInterval` | Numeric timing guidance; observed as `0`. |
| `timeout` | Numeric timing guidance; observed as `300`, not a measured expiry. |

**Dynamic, standalone 2026-10-31**: the challenge returned HTTP 200, `code: 0`,
and all required fields on official HTTPS Xiaomi hosts. Other fields were
`desc`, `description`, `qrTips`, `result`, and `sl`; the response set `uLocale`.
The owner approved the official page, and the subsequent flow completed
successfully as described below.

### 3.4 Poll for user approval

**Cross-checked static**: `M auth/qr.py::poll_qr_login`; `A
XMPassport.loginByLongPolling`.

```http
GET <lp returned by the challenge>
Cookie: deviceId=<same deviceId>
```

Use a bounded long read timeout and let the user approve through an official
Xiaomi surface. Consumed results:

- `userId`, `passToken`, `cUserId`, `ssecurity`, `nonce`, and `location`.
- `ssecurity` and `nonce` may instead occur in the JSON-valued
  `Extension-Pragma` response header.
- Nonzero `code` is an authentication failure; nonzero `securityStatus` and its
  `notificationUrl` require user action.

Do not log or persist the long-polling URL beyond the login attempt.

**Dynamic, standalone 2026-10-31**: one owner-approved poll returned HTTP 200,
`code: 0`, and `securityStatus: 0`. All six session fields were in the JSON
body; no `Extension-Pragma` fallback was needed. `notificationUrl` was empty.
Natural expiry, timeout, rejection, and approval variants remain unverified.

### 3.5 Exchange the result for a service token

**Cross-checked static**: `M auth/qr.py::exchange_sts`; `A
XMPassport.getServiceTokenByStsUrl` and `accountsdk/utils/Coder.java`.

Call the HTTPS `location` returned by the login result:

```http
GET <location>?clientSign=<signature>&_userIdNeedEncrypt=true
```

`clientSign` is Base64 of `SHA1("nonce=<login-nonce>&<ssecurity>")`, using the
login nonce and the original `ssecurity` string. This is separate from the
per-health-request nonce.

Do not follow redirects or forward account cookies. Read the service token from
the first response's `miothealth_serviceToken` cookie, with `serviceToken` as a
fallback. Retain only the cookies needed by the health transport. Reject a
non-HTTPS `location` and never log its query values.

**Dynamic, APK 3.59.2**: the phone/SMS login result exercised this STS exchange.
The calculated `clientSign` matched exactly, `_userIdNeedEncrypt` was `true`,
and the response used the `serviceToken` fallback name together with `userId`
and `cUserId`.

**Dynamic, standalone 2026-10-31**: the QR result established a session at
`https://sts-hlth.io.mi.com/healthapp/sts` with HTTP 200 and the same three
cookie names. Profile and daily aggregation then returned business `code: 0`.
The password security-confirmation exception in Section 3.2 remains open.

### 3.6 Renew with `passToken`

**Cross-checked static**: `M auth/renew.py`, `C` `_login_with_token`, `S`
`LoginWithToken`; `A XMPassport.loginByPassToken` and
`passport/utils/AccountHelper.java`.

```http
GET https://account.xiaomi.com/pass/serviceLogin?sid=miothealth&_json=true
Cookie: userId=<userId>; passToken=<passToken>; deviceId=<deviceId>
```

Do not follow redirects. Parse the same fields as QR approval and repeat the
STS exchange with the new `location`, nonce, and `ssecurity`.

Store a returned replacement `passToken` atomically with the new service
session; otherwise retain the existing one. Replace `serviceToken` and
`ssecurity` together only after the new STS exchange succeeds. Account code
`70016` indicates invalid credentials in the APK. Any security-confirmation
requirement needs interactive fallback.

**Dynamic, standalone 2026-10-31**: one proactive renewal returned HTTP 200,
`code: 0`, and `securityStatus: 0` without a password. The JSON body supplied
all session fields, and `Extension-Pragma` also contained `nonce`, `psecurity`,
and `ssecurity`. `passToken` was unchanged; the following `serviceToken` and
`ssecurity` changed. Post-renewal reads succeeded, and one immediate read with
the replaced service session also succeeded. Actual lifetimes, the duration of
old/new coexistence, later rotations, device-ID mismatch behavior, and natural
expiry recovery remain unverified.

## 4. Profile and Account Context

**Cross-checked static**: `M domains/profile.py`; `A
account/api/AccountService.java` and `account/api/bean/UserProfile.java`.

```http
GET https://hlth.io.mi.com/healthapp/user/get_miot_user_profile
```

Use the regional host and normal encrypted transport, but send **no `data`
parameter**. The signature path is `/user/get_miot_user_profile`, not the full
URL path. This exception is required.

The decrypted `result` object provides profile and attribution context. Consume
only fields with a project use case:

| Field | Use |
|---|---|
| `height`, `weight` | Current profile context, in centimeters and kilograms according to `M` runtime notes. |
| `daily_step_goal`, `daily_cal_goal` | Daily goals. |
| `regular_goal_list` | Goal entries; `field: 4` is reported by `M` as activity minutes. |
| `region` | Region hint; do not replace explicit region configuration blindly. |
| `dids` | Device identifiers associated with the profile; personal data. |
| `zone_name`, `zone_offset` | Profile timezone context when present. |

Names, birth dates, account IDs, icons, and other profile fields are personal
data but are not required for initial synchronization. Do not put a real
profile response in fixtures or logs.

## 5. Daily Watch Summaries

**Cross-checked static**: `M domains/steps.py`, `sleep.py`, and daily domains;
`A FitnessApiService.java`, `AggregateFitnessDataByTimeParam.java`, and cloud
report classes.

```http
GET https://hlth.io.mi.com/app/v1/data/get_aggregated_fitness_data_by_time
```

Business `data` object:

| Field | Required | Meaning |
|---|---|---|
| `tag` | Yes | Use `daily_report`. |
| `key` | Yes | One selected metric key below. |
| `start_time`, `end_time` | For bounded reads | Unix-second day bounds. |
| `reverse` | Recommended | `true` for newest first. |
| `limit` | Recommended | Page size; `50` is used by `M`. |
| `next_key` | Subsequent pages | Opaque cursor returned by the service. |

The `result` contains `data_list`, `has_more`, and `next_key`. Rows contain
`tag`, `key`, `sid`, `time`, `value`, `source_sid_list`, `zone_name`, and
`zone_offset`; `value` is a JSON string requiring a second parse.

Selected keys and consumed `value` fields:

| Key | Fields used by this project |
|---|---|
| `steps` | `steps`, `distance`, `calories` |
| `heart_rate` | `avg_hr`, `max_hr`, `min_hr`, `avg_rhr` |
| `sleep` | `total_duration`, `sleep_deep_duration`, `sleep_light_duration`, `sleep_rem_duration`, `sleep_awake_duration`, `segment_details` |
| `spo2` | `avg_spo2`, `max_spo2`, `min_spo2` |
| `stress` | `avg_stress`, `max_stress`, `min_stress`, `stress_scale` |

Sleep `segment_details` entries contain `bedtime`, `wake_up_time`, `duration`,
`timezone`, stage durations, and optional HR/SpO2 summaries. `stress_scale`
contains `relax`, `mild`, `moderate`, and `severe` durations. `M` reports sleep
and stress durations as minutes, distance as meters, and energy as kilocalories;
retain those as upstream-reported semantics pending local validation.

**Upstream runtime note**: the daily row's outer `time` is the UTC midnight of
the represented local date, and bounded selection is `(start_time, end_time]`.
Do not apply a global timezone shift to nested fields.

## 6. Raw Watch Metrics and Weight

**Cross-checked static**: `M domains/raw_window.py` and metric domains, `C`
`_fetch_key`, `S` weight reads; `A FitnessApiService.java`,
`GetFitnessDataByTime.java`, `FitnessDataModel.java`, and metric value classes.

```http
GET https://hlth.io.mi.com/app/v1/data/get_fitness_data_by_time
```

Business `data` object:

| Field | Required | Meaning |
|---|---|---|
| `key` | Yes | One selected raw key below. |
| `start_time`, `end_time` | For bounded reads | Unix-second bounds. Omit `start_time` for a backward full pull. |
| `reverse` | Recommended | `true` for newest first. |
| `next_key` | Subsequent pages | Opaque cursor returned by the service. |

The `result` contains `data_list`, `has_more`, and `next_key`. Raw rows consume
`key`, `sid`, `time`, `value`, `zone_name`, `zone_offset`, and `deleted`.
`value` is a JSON string.

Selected keys and core `value` fields:

| Key | Core fields and semantics |
|---|---|
| `heart_rate` | `time`, `bpm`, optional `type`; preserve the wire BPM unchanged. |
| `spo2` | `time`, `spo2`; percentage. |
| `stress` | `time`, `stress`; preserve the numeric score without inventing a level mapping. |
| `sleep` | `bedtime`, `wake_up_time`, `duration`, `timezone`, and `items` with start/end/state values. |
| `weight` | `time`, `weight`, `bmi`, plus available body-composition fields below. |

For weight and body composition, preserve `body_fat_rate`, `muscle_mass`,
`muscle_rate`, `body_moisture_mass`, `moisture_rate`, `bone_mass`,
`protein_mass`, `protein_rate`, `fat_mass`, `basal_metabolism`, `body_age`,
`body_score`, `visceral_fat`, `skeletal_muscle_mass`, and `bpm` when present.
`S` and `A WeightItem.java` support these field names, but this project has not
validated them with a real scale. Do not confuse `muscle_rate` with muscle mass
as `C` does in one adapter mapping, and do not turn missing measurements into
zero-valued measurements.

**Upstream runtime note**: dense raw keys can lose the bucket at or before
`start_time`. `M` therefore requests one day earlier and filters outer `time`
back to the desired inclusive window. Apply this compatibility measure to raw
HR, SpO2, stress, sleep, and weight reads until dynamic validation establishes
exact bucket behavior.

Sleep-stage codes are **unresolved**: `M` and `C` map some numeric states
differently. Preserve the original state numbers; do not expose a normalized
sleep-stage enum until verified against the current APK and real records.

## 7. Workout Summaries

**Cross-checked static**: `M domains/workouts.py`, `C`
`_fetch_sport_records_by_time`; `A FitnessApiService.java`,
`GetSportReportByTime.java`, `SportReportModel.java`, and `SportBasicReport.java`.

```http
GET https://hlth.io.mi.com/app/v1/data/get_sport_records_by_time
```

Business `data` object:

| Field | Required | Meaning |
|---|---|---|
| `start_time`, `end_time` | Yes for bounded reads | Unix-second workout-start bounds. |
| `reverse` | Recommended | `true`. |
| `limit` | Recommended | `50`. |
| `category` | No | Optional sport category filter; not needed initially. |
| `next_key` | Subsequent pages | Opaque cursor. |

The `result` contains `sport_records`, `has_more`, and `next_key`. Consume outer
`sid`, `key`, `category`, `time`, `zone_name`, `zone_offset`, and `deleted`.
Parse `value` for:

- `sport_type`, `start_time`, `end_time`, `duration`, and `timezone`.
- `distance`, `calories`, `total_cal`, and `steps`.
- `avg_hrm` and `max_hrm`.

`M` reports duration as seconds, distance as meters, energy as kilocalories, and
HR as BPM. **Upstream runtime note**: start selection is exclusive, so `M`
requests one second early and filters to the desired inclusive window. Skip
rows marked deleted. FDS workout details and GPS are outside this document.

## 8. Scale Users and Attributed Records

Use the general weight API in Section 6 for unified/manual weight reads. When
scale user attribution matters, also use this proxy. It provides `accountId`
and `did` context that a plain `weight` row does not reliably provide.

### 8.1 Shared proxy transport

**Cross-checked static**: `S` proxy implementation; `A ScaleService.java`,
`EcoProxyService.java`, and `ScaleRequest.java`.

```http
POST https://hlth.io.mi.com/app/v1/eco/api_proxy
Content-Type: application/x-www-form-urlencoded
```

Before the shared encryption layer, the business `data` object is:

```json
{"eco_api":"<operation>","params":"<JSON-encoded operation parameters>"}
```

`params` is a string containing JSON, not a nested object. The decrypted outer
`result` contains `resp`, which is another JSON string that must be parsed.

### 8.2 List scale users

Operation: `eco/scale/account/list`. **APK static**:
`ScaleRequest.getVirtualAccount`, `BindScaleRequest`, and `VirtualAccount.java`;
`S` has a commented older reference.

Operation parameters:

```json
{"uid":1000001,"did":"synthetic-device"}
```

`uid` is the Xiaomi account ID and `did` identifies the scale. The nested
response has `code`, `message`, and `result`, where `result` is a list of
accounts. Consume:

- `did`, `model`, `uid`, and `accountId` for attribution.
- `type` (`1` main account, `2` virtual account in the APK model).
- `name` only when a user-facing label is necessary; it is personal data.
- `height`, `birth`, and `weightTarget` only if a later body-composition
  interpretation requires them; do not collect them by default.

Do not assume the nested success code is the same as the general health `code:
0` envelope; the current parser returns this code to its caller without
normalizing it.

### 8.3 Pull attributed scale records

Operation: `eco/scale/record/pull`. **APK static**:
`ScaleRequest.pullRecord`, `MainViewModel.pullRecord`, and `RecordResult.java`.
This is the current APK path; no equivalent current open-source call chain was
reviewed.

Operation parameters:

| Field | Meaning |
|---|---|
| `uid` | Xiaomi account ID. |
| `did` | Scale device ID. |
| `pageSize` | Number of records; the observed app call uses `200`. |
| `createTime` | Pagination timestamp; start with the current synchronization boundary. |

The nested response uses `code: 200` and a `data` array, not the usual `result`
list. Each record can provide:

- Attribution: `id`, `deviceId`, `userId`, `accountId`, `model`, `sn`, and
  `fromSource`.
- Timing/versioning: `createTime`, `updateTime`, and `dataVersion`.
- Measurements: `weight`, `bmi`, `heartRate`, `bodyFatRate`, `muscleMass`,
  `boneMass`, `bodyMoistureMass`, `moistureRate`, `proteinMass`, `fatMass`,
  `basalMetabolism`, `visceralFat`, `bodyAge`, and `bodyScore`.
- Additional raw composition JSON in `data`; preserve it for model-specific
  fields rather than discarding it.

For pagination, the APK sorts records ascending by `createTime`, advances to
the oldest returned timestamp, and stops on an empty page. Apply the same
boundary carefully and deduplicate records sharing a timestamp. The initial
`createTime` value and exact inclusive/exclusive behavior need dynamic
validation. A possible attribution key is `(accountId, deviceId, createTime)`;
this is not yet a confirmed stable-record design.

Do not substitute `eco/scale/getData`, `eco/common/scale/getUserDataByPage`,
`eco/scale/record/list`, or `eco/common/scale/pull` without a separate
requirement and evidence review.

## 9. Synchronization Rules for the Initial Client

These are protocol constraints, not the project's final scheduler or database
policy:

1. Use an existing service session first, renew with `passToken` when needed,
   and request new owner-approved QR login when renewal is unavailable or
   fails. Do not attempt password or SMS recovery. Follow the
   [authentication state contract](mi-fitness-authentication-contract.md).
2. Replace `serviceToken` and `ssecurity` atomically after a successful renewal
   and STS exchange; retain or replace `passToken` according to the response.
3. Keep region explicit and use it consistently for host and `region_tag`.
4. Read profile and scale users before assigning device/user attribution.
5. Follow `next_key` until `has_more` is false, rejecting missing or repeated
   cursors to avoid infinite loops and silently truncated synchronization.
6. Use short time windows for dense metrics and apply the raw first-bucket
   compatibility rule. Persist only after the complete page/window outcome is
   known.
7. Preserve raw `sid`, `accountId`, `did`, source timestamps, deletion flags,
   and update versions where present. Do not treat outer time alone as a stable
   unique key.
8. Skip deleted rows and do not reinterpret zero, missing, or unsupported body
   measurements as real measurements.
9. Watermark APIs exist in the APK but are excluded until their semantics are
   needed and validated; time-window plus page-cursor reads are sufficient for
   this initial static contract.

## 10. Open Items Requiring Separate Dynamic Validation

- QR natural timeout/expiry, rejection, approval variants, and security
  confirmation; one owner-approved QR flow succeeded.
- Actual token lifetimes, natural expired-session 401 behavior, old/new session
  coexistence duration, later token rotations, and device-ID mismatch behavior.
- Natural long-term `passToken` failure and QR re-authentication recovery. Do
  not revoke credentials or repeatedly trigger account challenges to force
  them.
- Account region discovery and host behavior outside the verified China region.
- Exact time-window boundaries, raw bucket behavior, and cursor invariants.
- Sleep-stage numeric meanings and all model-specific body-composition units.
- Scale `record/pull` initial timestamp, boundary inclusivity, `updateTime`
  semantics, and multi-user coverage across scale models.
- Whether `dids` and `sid` are sufficient for friendly watch-device naming; no
  additional device-list API is justified yet.
- Deletion/correction propagation and durable deduplication keys.
- Production client behavior and long-term unattended operation; the validated
  independent flows used a disposable research harness, not application code.

These items must remain explicit in any later implementation. Static discovery,
APK 3.59.2 evidence, and the limited standalone experiments do not establish
watch support, scale support, body-fat accuracy, multi-user attribution, or
unattended long-term operation.
