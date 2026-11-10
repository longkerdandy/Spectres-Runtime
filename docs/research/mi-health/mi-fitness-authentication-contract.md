# Mi Fitness Authentication Implementation Contract

Status: v0.1.2 QR-only implementation contract, 2026-10-31. This is an input for
the next development milestone, not production code or a claim of long-term
unattended reliability.

Evidence applies to unmodified Mi Fitness `com.mi.health` 3.59.2, build 359002,
and separately identified standalone live requests on 2026-10-31. The only
validated account and host scope is explicitly configured China (`cn`). Other
regions are unverified and must not silently default to `cn`.

## 1. Selected Authentication Behavior

The owner-approved initial scope is **QR login and automatic `passToken`
renewal only**:

1. Reuse an existing health service session.
2. Renew it with `passToken` when a new service session is needed.
3. Request a new owner-approved QR login when renewal is unavailable, refused,
   or requires security interaction.

Password login, password recovery, and standalone SMS login are outside the
initial implementation. The application does not need to collect or retain an
account password. Earlier password observations in the API reference are
historical research evidence only.

Routine renewal is unattended, but the complete lifecycle is not: long-term
credential failure requires another manual QR approval.

## 2. Required Inputs and Retained Material

| Input or state | Requirement |
|---|---|
| `region` | Required explicit configuration; initial implementation accepts only `cn`. |
| `deviceId` | Required and stable across QR challenge, polling, and renewal. The harness used 16 uppercase hexadecimal characters. |
| `userId`, `cUserId` | Account/session identity returned by login or STS. Health reads observed here required only `cUserId`, not `userId`. |
| `passToken` | Long-lived renewal credential retained across service-session rotation. Never send it to health or STS hosts. |
| `serviceToken`, `ssecurity` | Health session credential and signing secret. Replace them together after renewal and STS succeed. |
| QR approval surface | Official HTTPS Xiaomi `loginUrl` or QR presentation; approval is manual. Never log the QR payload or `lp`. |

No login ID or password is an application input. Session material remains
sensitive even when response cookies omit security attributes.

## 3. State and Selection Model

```text
NO_SESSION → QR_CHALLENGE

QR_CHALLENGE → QR_WAITING_FOR_OWNER
  ├─ approval + complete session fields → STS_EXCHANGE
  ├─ security confirmation → OWNER_ACTION; no bypass
  └─ timeout / expiry / rejection → QR_FAILURE; a new challenge is required

STS_EXCHANGE → AUTHENTICATED
AUTHENTICATED → HEALTH_READ

HEALTH_READ HTTP 401 with a known-valid request signature
  → PASS_TOKEN_RENEWAL (at most one) → STS_EXCHANGE → one fresh-nonce retry

PASS_TOKEN_RENEWAL
  ├─ success → STS_EXCHANGE
  ├─ security confirmation → QR_CHALLENGE
  └─ unavailable / long-term credential refusal → QR_CHALLENGE

A second 401 after renewal/retry is a failure, not another renewal loop.
```

A malformed signature also produced HTTP 401 with plaintext JSON business
`code: 0`. Before selecting renewal, the client must ensure that its own request
construction and signature path are valid. Neither HTTP 401 nor business
`code: 0` alone proves expiry or read success; success requires an expected HTTP
status, decryptable envelope, business `code: 0`, and the expected result shape.

## 4. Wire Contracts

### 4.1 QR challenge and polling

`GET https://account.xiaomi.com/longPolling/loginUrl?sid=miothealth&_json=true`
returns:

| Field | Observed type | Handling |
|---|---|---|
| `code` | integer | Require `0`. |
| `loginUrl`, `qr`, `lp` | strings | Require official HTTPS Xiaomi URLs; treat all as sensitive. |
| `timeInterval` | integer | Observed `0`; retain as server timing guidance. |
| `timeout` | integer | Observed `300`; do not present it as a measured challenge lifetime. |
| `desc`, `description`, `qrTips`, `result`, `sl` | strings | Optional for the initial client. |

Send the same `deviceId` to the challenge and the server-provided `lp`. Poll
once with a bounded read timeout. The harness used 120 seconds and the owner
approved within that window. Cancellation must stop waiting and discard the
challenge. Do not persist `lp` beyond the attempt.

### 4.2 Common login result

Required session-establishment fields:

| Field | Observed location |
|---|---|
| `userId`, `cUserId`, `passToken` | JSON body; account cookies may also carry them. Renewal may retain known values when omitted. |
| `ssecurity`, `nonce` | JSON body, with JSON-valued `Extension-Pragma` as fallback. |
| `location` | JSON body; require HTTPS and the expected regional STS host. |

QR approval and renewal both returned all six in the body. Renewal additionally
returned `nonce`, `psecurity`, and `ssecurity` in `Extension-Pragma`. Keep nonce
as exact decimal text; do not coerce through a floating-point type.

### 4.3 STS and health session

Call `location` with `clientSign=Base64(SHA1("nonce=<nonce>&<ssecurity>"))` and
`_userIdNeedEncrypt=true`. Do not follow redirects or send account cookies.
Accept `miothealth_serviceToken`, falling back to `serviceToken`.

The QR and renewal STS responses used HTTP 200, path `/healthapp/sts` on
`sts-hlth.io.mi.com`, and cookies `userId`, `cUserId`, and `serviceToken`. The
observed cookies had path `/`, host-only STS domain, and no Secure, HttpOnly,
SameSite, Expires, or Max-Age attributes.

Health reads in the standalone harness sent only `serviceToken` and `cUserId`
cookies plus `region_tag: cn`. Profile uses no `data` parameter and signature
path `/user/get_miot_user_profile`. Use a fresh health nonce for every request.

### 4.4 Renewal and atomic rotation

`GET /pass/serviceLogin?sid=miothealth&_json=true` sends `userId`, `passToken`,
and the same `deviceId`. It sends no password and requires no new QR approval
on the observed success path. Parse the common login result and perform a new
STS exchange.

Observed once:

- `passToken` remained unchanged.
- `serviceToken` changed.
- `ssecurity` changed.
- Post-renewal Profile and daily aggregation returned business `code: 0`.
- The replaced service session remained valid for one immediate control read.

Persist the new `serviceToken` and `ssecurity` together only after STS succeeds
and required fields are present. Retain the old session if renewal or STS fails.
Retain `passToken` when unchanged, or replace it in the same transaction if a
future response rotates it. Do not infer an old-token grace period from one
immediate control request.

## 5. Errors, Timeouts, and Redirects

| Observation | Required selection |
|---|---|
| Nonzero QR/login `securityStatus` | Owner interaction; no bypass or automatic repeated attempt. |
| Invalid health signature | Observed HTTP 401, plaintext JSON `code: 0`; do not renew in a loop. |
| Successful health read | HTTP 200 and decrypted business `code: 0` with expected result schema. |
| QR timeout/expiry | Require a fresh challenge; exact live expiry behavior remains open. |
| Renewal unavailable or refused | Request new QR approval; do not attempt password recovery. |
| Natural session or `passToken` expiry | Unobserved; keep renewal/retry bounded and test recovery later. |

Never automatically follow account or STS redirects. Reject non-HTTPS
`location` values and unexpected hosts. Do not forward account cookies to STS
or health services. Do not log tokens, secret headers, complete sensitive URLs,
account identifiers, QR payloads, or real health values.

## 6. Synthetic Fixtures

The original Edge repository's `tests/fixtures/auth/` files contain only
synthetic identifiers, tokens, URLs, and values. Their `manifest.json`
identifies the evidence shape each file represents. QR challenge/approval,
renewal, STS, health success, and invalid-signature fixtures support the initial
implementation. Copy individual fixtures into Extension tests only when those
tests consume them.

Password fixtures preserve earlier research shapes only. In particular,
`password-success-unverified.json` is not a recorded success and is not an
initial implementation requirement.

## 7. Remaining Limits

1. QR natural expiry, rejection, approval variants, and security confirmation
   remain unvalidated.
2. Actual session expiration, long-term `passToken` failure, and the subsequent
   QR recovery path were not exercised naturally.
3. Only one QR login and one proactive renewal were tested. Device-ID mismatch,
   future rotations, old-session coexistence duration, and other accounts remain
   unverified.
4. Only China is in initial scope. Production authentication code is part of
   the next milestone, not the dynamic-validation milestone.
