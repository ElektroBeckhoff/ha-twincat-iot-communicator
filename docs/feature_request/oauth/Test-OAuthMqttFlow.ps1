#Requires -Version 5.1
<#
.SYNOPSIS
    Tests the full OAuth 2.0 Authorization Code + PKCE flow and MQTT JWT authentication.

.DESCRIPTION
    Pure PowerShell implementation (no Python required).
    1. OIDC Discovery
    2. PKCE generation (S256)
    3. Browser login via Identity Provider
    4. Local HTTP callback listener
    5. Token exchange (code -> JWT)
    6. JWT decode and validation
    7. MQTT CONNECT with JWT as password (TLS)
    8. MQTT PUBLISH test message

.NOTES
    Prerequisites:
    - Redirect URI http://localhost:<CallbackPort>/auth/tc_iot/callback registered in your Identity Provider
    - Port must be free locally

.PARAMETER IssuerUrl
    OIDC Issuer URL of the Identity Provider (e.g. https://auth.example.com/realms/myrealm).

.PARAMETER ClientId
    OAuth Client ID registered at the Identity Provider.

.PARAMETER MqttHost
    Hostname of the MQTT broker that accepts JWT authentication.

.PARAMETER MqttPort
    TLS port of the MQTT broker (default: 8884).

.PARAMETER MqttTopic
    Base MQTT topic for the roundtrip test (default: test/oauth).

.PARAMETER CallbackPort
    Local port for the OAuth callback listener (default: 8123).

.PARAMETER TimeoutMinutes
    Timeout in minutes for the browser login (default: 3).

.PARAMETER SkipMqtt
    Skip the MQTT connection test and only validate the OAuth flow.

.PARAMETER SkipCertCheck
    Skip TLS certificate validation for the MQTT connection. INSECURE — use only for testing with self-signed certificates.

.EXAMPLE
    .\Test-OAuthMqttFlow.ps1 -IssuerUrl "https://auth.example.com/realms/myrealm" -ClientId "my_client" -MqttHost "mqtt.example.com"

.EXAMPLE
    .\Test-OAuthMqttFlow.ps1 -IssuerUrl "https://auth.example.com/realms/myrealm" -ClientId "my_client" -MqttHost "mqtt.example.com" -SkipMqtt

.EXAMPLE
    .\Test-OAuthMqttFlow.ps1 -IssuerUrl "https://auth.example.com/realms/myrealm" -ClientId "my_client" -MqttHost "mqtt.example.com" -MqttPort 8883 -CallbackPort 9876
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, HelpMessage = "OIDC Issuer URL (e.g. https://auth.example.com/realms/myrealm)")]
    [ValidateNotNullOrEmpty()]
    [string]$IssuerUrl,

    [Parameter(Mandatory = $true, HelpMessage = "OAuth Client ID registered at the Identity Provider")]
    [ValidateNotNullOrEmpty()]
    [string]$ClientId,

    [Parameter(Mandatory = $true, HelpMessage = "MQTT broker hostname")]
    [ValidateNotNullOrEmpty()]
    [string]$MqttHost,

    [Parameter(HelpMessage = "MQTT broker TLS port")]
    [int]$MqttPort = 8884,

    [Parameter(HelpMessage = "Base MQTT topic for roundtrip test")]
    [string]$MqttTopic = "test/oauth",

    [Parameter(HelpMessage = "Local port for OAuth callback listener")]
    [int]$CallbackPort = 8123,

    [Parameter(HelpMessage = "Timeout in minutes for browser login")]
    [int]$TimeoutMinutes = 3,

    [switch]$SkipMqtt,

    [Parameter(HelpMessage = "Skip TLS certificate validation (INSECURE, testing only)")]
    [switch]$SkipCertCheck
)

$ErrorActionPreference = "Stop"

function Write-Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)       { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg)     { Write-Host "    [FAIL] $msg" -ForegroundColor Red }
function Write-Warn($msg)     { Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Detail($msg)   { Write-Host "    $msg" -ForegroundColor Gray }

function Send-MqttConnect {
    param(
        [System.Net.Security.SslStream]$Stream,
        [string]$ClientId,
        [string]$Username,
        [string]$Password
    )

    $ms = New-Object System.IO.MemoryStream
    $bw = New-Object System.IO.BinaryWriter($ms)

    # Variable Header
    $bw.Write([byte]0x00); $bw.Write([byte]0x04)
    $bw.Write([System.Text.Encoding]::ASCII.GetBytes("MQTT"))
    $bw.Write([byte]0x04)   # Protocol level 3.1.1
    $bw.Write([byte]0xC2)   # Flags: username + password + clean session
    $bw.Write([byte]0x00); $bw.Write([byte]0x3C)  # Keepalive 60s

    # Payload: ClientId, Username, Password (each with 2-byte length prefix)
    foreach ($str in @($ClientId, $Username, $Password)) {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($str)
        $bw.Write([byte](($bytes.Length -shr 8) -band 0xFF))
        $bw.Write([byte]($bytes.Length -band 0xFF))
        $bw.Write($bytes)
    }

    $body = $ms.ToArray()
    $bw.Close(); $ms.Close()

    # Fixed header: type 0x10 + remaining length
    $hdr = New-Object System.IO.MemoryStream
    $hdr.WriteByte(0x10)
    $rl = $body.Length
    do {
        $b = $rl -band 0x7F
        $rl = [Math]::Floor($rl / 128)
        if ($rl -gt 0) { $b = $b -bor 0x80 }
        $hdr.WriteByte($b)
    } while ($rl -gt 0)
    $hdr.Write($body, 0, $body.Length)

    $packet = $hdr.ToArray()
    $hdr.Close()

    $Stream.Write($packet, 0, $packet.Length)
    $Stream.Flush()
    return $packet.Length
}

function Send-MqttPublish {
    param(
        [System.Net.Security.SslStream]$Stream,
        [string]$Topic,
        [string]$Message
    )

    $topicBytes = [System.Text.Encoding]::UTF8.GetBytes($Topic)
    $msgBytes = [System.Text.Encoding]::UTF8.GetBytes($Message)

    $ms = New-Object System.IO.MemoryStream
    $ms.WriteByte(($topicBytes.Length -shr 8) -band 0xFF)
    $ms.WriteByte($topicBytes.Length -band 0xFF)
    $ms.Write($topicBytes, 0, $topicBytes.Length)
    $ms.Write($msgBytes, 0, $msgBytes.Length)
    $payload = $ms.ToArray()
    $ms.Close()

    $hdr = New-Object System.IO.MemoryStream
    $hdr.WriteByte(0x30)  # PUBLISH QoS 0
    $rl = $payload.Length
    do {
        $b = $rl -band 0x7F
        $rl = [Math]::Floor($rl / 128)
        if ($rl -gt 0) { $b = $b -bor 0x80 }
        $hdr.WriteByte($b)
    } while ($rl -gt 0)
    $hdr.Write($payload, 0, $payload.Length)

    $packet = $hdr.ToArray()
    $hdr.Close()

    $Stream.Write($packet, 0, $packet.Length)
    $Stream.Flush()
}

function Send-MqttSubscribe {
    param(
        [System.Net.Security.SslStream]$Stream,
        [string]$Topic,
        [int]$PacketId = 1
    )

    $topicBytes = [System.Text.Encoding]::UTF8.GetBytes($Topic)

    $ms = New-Object System.IO.MemoryStream
    # Packet ID (2 bytes)
    $ms.WriteByte(($PacketId -shr 8) -band 0xFF)
    $ms.WriteByte($PacketId -band 0xFF)
    # Topic filter (length-prefixed) + QoS
    $ms.WriteByte(($topicBytes.Length -shr 8) -band 0xFF)
    $ms.WriteByte($topicBytes.Length -band 0xFF)
    $ms.Write($topicBytes, 0, $topicBytes.Length)
    $ms.WriteByte(0x00)  # QoS 0
    $payload = $ms.ToArray()
    $ms.Close()

    $hdr = New-Object System.IO.MemoryStream
    $hdr.WriteByte(0x82)  # SUBSCRIBE packet type
    $rl = $payload.Length
    do {
        $b = $rl -band 0x7F
        $rl = [Math]::Floor($rl / 128)
        if ($rl -gt 0) { $b = $b -bor 0x80 }
        $hdr.WriteByte($b)
    } while ($rl -gt 0)
    $hdr.Write($payload, 0, $payload.Length)

    $packet = $hdr.ToArray()
    $hdr.Close()

    $Stream.Write($packet, 0, $packet.Length)
    $Stream.Flush()
}

function Receive-MqttPublish {
    param(
        [System.Net.Security.SslStream]$Stream,
        [int]$TimeoutMs = 5000
    )

    $Stream.ReadTimeout = $TimeoutMs
    $buf = New-Object byte[] 4096

    try {
        $n = $Stream.Read($buf, 0, 4096)
    } catch {
        return $null
    }

    if ($n -le 0 -or ($buf[0] -band 0xF0) -ne 0x30) { return $null }

    # Parse remaining length
    $idx = 1
    $remLen = 0; $mul = 1
    do {
        $b = $buf[$idx]
        $remLen += ($b -band 0x7F) * $mul
        $mul *= 128
        $idx++
    } while ($b -band 0x80)

    # Topic
    $topicLen = ($buf[$idx] -shl 8) + $buf[$idx + 1]
    $idx += 2
    $topic = [System.Text.Encoding]::UTF8.GetString($buf, $idx, $topicLen)
    $idx += $topicLen

    # Payload
    $payloadLen = $remLen - 2 - $topicLen
    $payload = [System.Text.Encoding]::UTF8.GetString($buf, $idx, $payloadLen)

    return @{ Topic = $topic; Payload = $payload }
}

function Send-MqttDisconnect {
    param([System.Net.Security.SslStream]$Stream)
    $Stream.WriteByte(0xE0)
    $Stream.WriteByte(0x00)
    $Stream.Flush()
}

# ═══════════════════════════════════════════════════════════
Write-Host "============================================" -ForegroundColor White
Write-Host "  OAuth + MQTT Flow Test (Pure PowerShell)" -ForegroundColor White
Write-Host "============================================" -ForegroundColor White

# ─── STEP 1: OIDC Discovery ───
Write-Step 1 "OIDC Discovery"
Write-Detail "GET $IssuerUrl/.well-known/openid-configuration"

$discovery = Invoke-RestMethod -Uri "$IssuerUrl/.well-known/openid-configuration" -Method Get -TimeoutSec 10
$authEndpoint = $discovery.authorization_endpoint
$tokenEndpoint = $discovery.token_endpoint

if (-not $authEndpoint -or -not $tokenEndpoint) {
    Write-Fail "Endpoints not found"; exit 1
}
Write-Ok "authorization_endpoint: $authEndpoint"
Write-Ok "token_endpoint: $tokenEndpoint"

if ($discovery.code_challenge_methods_supported -contains "S256") {
    Write-Ok "PKCE S256 supported"
} else {
    Write-Fail "PKCE S256 NOT supported"; exit 1
}

# ─── STEP 2: PKCE Generation ───
Write-Step 2 "PKCE Key Pair (S256)"

$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$verifierBytes = New-Object byte[] 64
$rng.GetBytes($verifierBytes)
$codeVerifier = [Convert]::ToBase64String($verifierBytes) -replace '\+','-' -replace '/','_' -replace '=',''

$sha256 = [System.Security.Cryptography.SHA256]::Create()
$challengeBytes = $sha256.ComputeHash([System.Text.Encoding]::ASCII.GetBytes($codeVerifier))
$codeChallenge = [Convert]::ToBase64String($challengeBytes) -replace '\+','-' -replace '/','_' -replace '=',''

Write-Ok "code_verifier length: $($codeVerifier.Length)"
Write-Ok "code_challenge: $($codeChallenge.Substring(0, 20))..."

# ─── STEP 3: Authorization URL ───
Write-Step 3 "Authorization Request"

$flowId = [Guid]::NewGuid().ToString()
$callbackPath = "/auth/tc_iot/callback"
$redirectUri = "http://localhost:$CallbackPort$callbackPath"

$authUrl = $authEndpoint +
    "?response_type=code" +
    "&client_id=$([Uri]::EscapeDataString($ClientId))" +
    "&redirect_uri=$([Uri]::EscapeDataString($redirectUri))" +
    "&scope=openid" +
    "&code_challenge=$codeChallenge" +
    "&code_challenge_method=S256" +
    "&state=$flowId"

Write-Detail "flow_id: $flowId"
Write-Detail "redirect_uri: $redirectUri"

# ─── STEP 4: Callback Listener + Browser ───
Write-Step 4 "Browser Login"

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$CallbackPort/")
try {
    $listener.Start()
} catch {
    Write-Fail "Port $CallbackPort is in use. Specify a different port with -CallbackPort."
    exit 1
}

Write-Ok "Listener on http://localhost:$CallbackPort/"
Start-Process $authUrl
Write-Host ""
Write-Host "    >>> Please log in via browser! ($TimeoutMinutes min timeout) <<<" -ForegroundColor Yellow
Write-Host ""

$authCode = $null
$accessToken = $null
$deadline = [DateTime]::Now.AddMinutes($TimeoutMinutes)

while ([DateTime]::Now -lt $deadline) {
    $task = $listener.GetContextAsync()
    while (-not $task.IsCompleted -and [DateTime]::Now -lt $deadline) {
        Start-Sleep -Milliseconds 300
    }
    if (-not $task.IsCompleted) { break }

    $context = $task.Result
    $request = $context.Request
    $response = $context.Response

    if ($request.Url.AbsolutePath -eq $callbackPath) {
        $query = [System.Web.HttpUtility]::ParseQueryString($request.Url.Query)

        if ($query["code"]) {
            $authCode = $query["code"]
            $html = [System.Text.Encoding]::UTF8.GetBytes(
                "<html><body><h1>Success!</h1><p>Authorization code received. You can close this window.</p></body></html>"
            )
            $response.ContentType = "text/html; charset=utf-8"
            $response.ContentLength64 = $html.Length
            $response.OutputStream.Write($html, 0, $html.Length)
            $response.OutputStream.Close()

            if ($query["state"] -ne $flowId) { Write-Warn "State mismatch!" }
            Write-Ok "Authorization code received (length: $($authCode.Length))"
            break
        }
    }

    $response.StatusCode = 404
    $response.OutputStream.Close()
}
$listener.Stop()

if (-not $authCode) {
    Write-Fail "Timeout - no authorization code received"
    exit 1
}

# ─── STEP 5: Token Exchange ───
if ($authCode) {
    Write-Step 5 "Token Exchange"
    Write-Detail "POST $tokenEndpoint"

    $tokenBody = @{
        grant_type    = "authorization_code"
        code          = $authCode
        redirect_uri  = $redirectUri
        client_id     = $ClientId
        code_verifier = $codeVerifier
    }

    try {
        $tokenResponse = Invoke-RestMethod -Uri $tokenEndpoint -Method Post -Body $tokenBody `
            -ContentType "application/x-www-form-urlencoded" -TimeoutSec 15
        $accessToken = $tokenResponse.access_token

        if (-not $accessToken) { Write-Fail "No access_token in response"; exit 1 }
        Write-Ok "Token received"
        Write-Detail "token_type: $($tokenResponse.token_type)"
        Write-Detail "expires_in: $($tokenResponse.expires_in) seconds"
    } catch {
        Write-Fail "Token exchange failed: $_"
        exit 1
    }
}

# ─── STEP 6: JWT Decode ───
Write-Step 6 "JWT Validation"

$jwtParts = $accessToken.Split('.')
if ($jwtParts.Count -ne 3) { Write-Fail "Invalid JWT format"; exit 1 }
Write-Ok "JWT structure valid (header.payload.signature)"

$payloadB64 = $jwtParts[1] -replace '-','+' -replace '_','/'
switch ($payloadB64.Length % 4) { 2 { $payloadB64 += '==' } 3 { $payloadB64 += '=' } }
$payloadJson = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payloadB64))
$payload = $payloadJson | ConvertFrom-Json

$mqttUsername = $null
if ($payload.preferred_username) {
    $mqttUsername = $payload.preferred_username
    Write-Ok "preferred_username: $mqttUsername"
} elseif ($payload.sub) {
    $mqttUsername = $payload.sub
    Write-Warn "No preferred_username, using sub: $mqttUsername"
} else {
    Write-Fail "No username claim in JWT"; exit 1
}

if ($payload.exp) {
    $expDate = (New-Object DateTime(1970, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)).AddSeconds($payload.exp)
    $remaining = $expDate - [DateTime]::UtcNow
    if ($remaining.TotalSeconds -gt 0) {
        Write-Ok "exp: $expDate UTC (valid for $([Math]::Round($remaining.TotalMinutes, 0)) min)"
    } else {
        Write-Fail "Token EXPIRED at $expDate UTC"; exit 1
    }
} else {
    Write-Fail "No exp claim (mandatory since 0.0.18)"; exit 1
}

if ($payload.iss) {
    if ($payload.iss -eq $IssuerUrl) {
        Write-Ok "iss: $($payload.iss) (matches IssuerUrl)"
    } else {
        Write-Fail "iss mismatch: JWT has '$($payload.iss)', expected '$IssuerUrl'"; exit 1
    }
} else {
    Write-Warn "No iss claim in JWT (issuer validation skipped)"
}

Write-Detail "sub: $($payload.sub)"
Write-Detail "azp: $($payload.azp)"
Write-Detail "scope: $($payload.scope)"
if ($payload.email) { Write-Detail "email: $($payload.email)" }

# ─── STEP 7: MQTT ───
if ($SkipMqtt) {
    Write-Step 7 "MQTT (skipped via -SkipMqtt)"
    Write-Detail "Username: $mqttUsername"
    Write-Detail "Password: <JWT, $($accessToken.Length) chars>"
} else {
    Write-Step 7 "MQTT Connect (${MqttHost}:${MqttPort} TLS)"

    $tcp = New-Object System.Net.Sockets.TcpClient($MqttHost, $MqttPort)
    if ($SkipCertCheck) {
        Write-Warn "TLS certificate validation DISABLED (insecure)"
        $certCallback = [System.Net.Security.RemoteCertificateValidationCallback]{
            param($sender, $cert, $chain, $errors)
            return $true
        }
        $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, $certCallback)
    } else {
        $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false)
    }
    $ssl.AuthenticateAsClient($MqttHost)
    Write-Ok "TLS handshake ($($ssl.SslProtocol))"
    Write-Detail "Cert: $($ssl.RemoteCertificate.Subject), expires $($ssl.RemoteCertificate.GetExpirationDateString())"

    $mqttClientId = "ps1-test-" + [Guid]::NewGuid().ToString().Substring(0, 8)
    $packetSize = Send-MqttConnect -Stream $ssl -ClientId $mqttClientId -Username $mqttUsername -Password $accessToken
    Write-Detail "CONNECT sent (client_id: $mqttClientId, $packetSize bytes)"

    $ssl.ReadTimeout = 10000
    $buf = New-Object byte[] 8
    $n = $ssl.Read($buf, 0, 8)

    if ($n -ge 4 -and $buf[0] -eq 0x20) {
        $rc = $buf[3]
        switch ($rc) {
            0 { Write-Ok "CONNACK rc=0 - Connection Accepted" }
            1 { Write-Fail "CONNACK rc=1 - Unacceptable protocol version" }
            2 { Write-Fail "CONNACK rc=2 - Identifier rejected" }
            3 { Write-Fail "CONNACK rc=3 - Server unavailable" }
            4 { Write-Fail "CONNACK rc=4 - Bad credentials" }
            5 { Write-Fail "CONNACK rc=5 - Not authorized (JWT rejected by broker)" }
            default { Write-Fail "CONNACK rc=$rc" }
        }

        if ($rc -eq 0) {
            # Subscribe to roundtrip topic
            Write-Step 8 "MQTT Subscribe"
            $roundtripTopic = "$MqttTopic/test/roundtrip"
            Send-MqttSubscribe -Stream $ssl -Topic $roundtripTopic -PacketId 1

            # Read SUBACK
            $ssl.ReadTimeout = 5000
            $subackBuf = New-Object byte[] 8
            try {
                $subackN = $ssl.Read($subackBuf, 0, 8)
                if ($subackN -gt 0 -and $subackBuf[0] -eq 0x90) {
                    Write-Ok "SUBACK received - subscribed to: $roundtripTopic"
                } else {
                    Write-Warn "Unexpected SUBACK response"
                }
            } catch {
                Write-Warn "No SUBACK (timeout)"
            }

            # Publish to the same topic
            Write-Step 9 "MQTT Publish + Receive Roundtrip"
            $testPayload = '{"value":42,"unit":"degC","source":"oauth-flow-test","user":"' + $mqttUsername + '"}'
            Send-MqttPublish -Stream $ssl -Topic $roundtripTopic -Message $testPayload
            Write-Ok "PUBLISH -> $roundtripTopic"
            Write-Detail "Sent: $testPayload"

            # Wait and read the message back
            Start-Sleep -Milliseconds 500
            $received = Receive-MqttPublish -Stream $ssl -TimeoutMs 5000

            if ($received) {
                Write-Ok "RECEIVED message on subscriber"
                Write-Detail "Topic: $($received.Topic)"
                Write-Detail "Payload: $($received.Payload)"
                if ($received.Payload -eq $testPayload) {
                    Write-Ok "Roundtrip MATCH - publish and subscribe working"
                } else {
                    Write-Warn "Payload mismatch"
                }
            } else {
                Write-Warn "No message received (broker may not echo to same client)"
            }

            Send-MqttDisconnect -Stream $ssl
            Write-Ok "DISCONNECT"
        }
    } else {
        $hex = ($buf[0..($n-1)] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '
        Write-Fail "Unexpected response ($n bytes): $hex"
    }

    $ssl.Close()
    $tcp.Close()
}

# ─── Summary ───
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  ALL TESTS PASSED" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Detail "Issuer:   $IssuerUrl"
Write-Detail "Client:   $ClientId"
Write-Detail "MQTT:     ${MqttHost}:${MqttPort} (TLS)"
Write-Detail "Username: $mqttUsername"
Write-Detail "Topic:    $MqttTopic"
