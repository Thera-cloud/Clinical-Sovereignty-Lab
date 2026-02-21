---
name: Deployment and App Store Readiness
overview: The backend and infrastructure score 9/10 for production readiness, but iOS and Android have critical blockers that must be resolved before app store submission. This plan identifies every remaining gap.
todos:
  - id: fix-bundle-id
    content: Change iOS bundle ID from com.example.littleNate to real bundle ID and add privacy manifest fields
    status: completed
  - id: fix-android-config
    content: Verify Android build.gradle (applicationId, targetSdk 34+, signing config) and disable cleartext traffic
    status: completed
  - id: fix-hardcoded-ips
    content: Remove hardcoded 10.0.0.81 defaults from config.py, network.py, and security service files
    status: completed
  - id: production-credentials
    content: Ensure all .env placeholder values are replaced with real production credentials (Azure, Stripe, SendGrid, Twilio, JWT)
    status: completed
  - id: docker-resource-limits
    content: Add CPU/memory limits to docker-compose.prod.yml services
    status: completed
  - id: run-test-suite
    content: Run full pytest suite and flutter analyze to verify no regressions before deploy
    status: completed
isProject: false
---

# Deployment and App Store Readiness Assessment

## What IS Ready

- **Backend Infrastructure**: Docker Compose production config, health checks on all 5 services, named volumes, network isolation
- **Nginx**: SSL/TLS 1.2+, HSTS, rate limiting, subdomain routing for all 3 portals, catch-all block
- **Legal Compliance**: Privacy policy (v13.0) and Terms of Use both complete and comprehensive -- CCPA, BIPA, CUBI, COPPA, CA AB 489 all covered
- **Deployment Script**: `deploy.sh` uses targeted `scp` and `rsync` without `--delete`
- **CI/CD Pipeline**: `.github/workflows/deploy.yml` exists with test, build, staging bake, and production deploy stages
- **Backend Tests**: 27 test files + integration suite covering security, coherence, ZEFCP, Quakete, and core services
- **All Core Features**: 41+ plans completed -- campaign system, deletion safety, account management, sentinel, abuse detection, TOTP/WebAuthn, deadman switch, batch family invite, etc.

---

## CRITICAL BLOCKERS (Must Fix)

### 1. iOS Bundle ID

[mobile/ios/Runner/Info.plist](mobile/ios/Runner/Info.plist) has `com.example.littleNate` -- Apple will reject this instantly. Must change to a real bundle ID like `net.sovereignsanctuary.littlenate` and register it in Apple Developer portal.

### 2. iOS Privacy Manifest (Required for iOS 17+)

Missing from Info.plist:

- `NSPrivacyCollectedDataTypes` -- Apple requires declaring what data the app collects
- `NSPrivacyAccessedAPITypes` -- Must declare use of required reason APIs (UserDefaults, file timestamp, etc.)
- `ITSAppUsesNonExemptEncryption` -- Must declare encryption usage (the app uses AES/TLS)

Without these, Apple will reject the binary during App Store Connect upload.

### 3. Android Build Configuration

The `build.gradle` needs verification for:

- `applicationId` (the Play Store package name)
- `minSdkVersion` / `targetSdkVersion` (Google requires targetSdk 34+ as of late 2025)
- `versionCode` / `versionName`
- Signing config for release builds

Also: [mobile/android/app/src/main/AndroidManifest.xml](mobile/android/app/src/main/AndroidManifest.xml) has `android:usesCleartextTraffic="true"` -- should be `false` for production since all endpoints use HTTPS.

### 4. Hardcoded Internal IPs

`10.0.0.81` is hardcoded as defaults in multiple files:

- [backend/app/config.py](backend/app/config.py) -- `SERVER_HOST`, `BASE_URL`, `WS_URL`, `POSTGRES_HOST`, `REDIS_HOST`
- `backend/app/config/network.py` -- Redundant config with same hardcoded IPs
- `backend/app/services/security/canary_credentials.py` -- DB connection string
- `backend/app/services/security/dependency_quarantine.py` -- Both dev and production IPs

These work because Docker overrides them via env vars, but they are a deployment risk if env vars are ever missing.

---

## SHOULD-FIX BEFORE DEPLOY

### 5. Production Credentials

The `.env.template` has ~15 placeholder values that need real production credentials:

- Azure OpenAI API key and endpoint
- PostgreSQL and Redis passwords
- JWT secret
- SendGrid API key + template IDs
- Twilio SID/token/phone
- Zoom account credentials
- Social media platform OAuth tokens (for SkyEye)
- Stripe keys (if payments enabled)

### 6. Flutter Test Coverage

Only 5 test files exist for the mobile app (mostly ZEFCP unit tests). Missing:

- Login/auth flow tests
- WebSocket connection tests
- Session management tests
- Family invite flow tests

### 7. Docker Resource Limits

`docker-compose.prod.yml` has no CPU/memory limits -- a runaway process could take down the entire server.

### 8. CI/CD Pipeline Gaps

`.github/workflows/deploy.yml` has some placeholder steps:

- Security scanning (Trivy/Snyk) not fully wired
- Staging deployment is a bake timer, not a real staging environment

---

## NOT-STARTED FEATURES (4 Plans, 0 Code)

These are features that were planned but never built. They are NOT blockers for launch, but represent incomplete product vision:

1. **DOJO Internet Search Security** (7 todos) -- Search proxy with coach approval, rate limiting, content filtering
2. **Little Nate 3D Avatar** (10 todos) -- Voice-driven animated avatar for Top Tier clients
3. **Coach Command Verification** (6 todos) -- License verification, background checks for coaches
4. **Admin Portal Tier Breakdown** (7 todos) -- Tier analytics dashboard with grouping

---

## App Store Submission Checklist

Before iOS App Store:

- Fix bundle ID
- Add privacy manifest
- Add encryption declaration
- Create app icon set (1024x1024 + all sizes)
- Write App Store description, keywords, screenshots
- Set up TestFlight for beta testing
- Apple Developer account ($99/year)

Before Google Play Store:

- Verify build.gradle configuration
- Disable cleartext traffic
- Create signing keystore
- Write Play Store listing
- Set up internal/closed testing track
- Google Developer account ($25 one-time)

Before production deploy:

- Replace all placeholder credentials in .env
- Run full test suite (`pytest backend/tests/ -v`)
- Run `flutter build web` and `flutter build ios --release`
- Apply all 46 database migrations to production PostgreSQL
- Verify all 5 containers start healthy

