# Flutter Build Flavors — Mobile App White-Labeling

## Technical Readiness Document

**Purpose:** Demonstrate that mobile app white-labeling is a solved engineering problem using Flutter's native build flavor system. No research required — this is standard Flutter architecture used by thousands of production apps.

---

## 1. Concept

The RAMP mobile app (`ramp_poster`) is built with Flutter — a single codebase that compiles to both iOS and Android. Flutter's **build flavor** system lets us produce multiple differently-branded apps from the same source code.

| Aspect | Detail |
|--------|--------|
| Shared code | 95% — all screens, services, models, providers, widgets |
| Per-flavor config | 5% — app name, icon, splash, colors, API URL, bundle ID |
| Build output | One APK/IPA per partner, each a fully independent app |
| App Store presence | Each partner's app appears as a separate listing |

**Key insight:** Adding a new partner's branded app is a configuration task (2-4 hours), not a development task. No code changes required.

---

## 2. Project Structure

```
ramp_poster/
├── lib/                              # SHARED CODE (95%)
│   ├── main.dart                     # App entry point (reads flavor config)
│   ├── config/
│   │   └── flavor_config.dart        # Runtime flavor configuration class
│   ├── screens/
│   │   ├── login_screen.dart
│   │   ├── queue_screen.dart         # Draft queue (approve/reject/post)
│   │   ├── detail_screen.dart        # Draft detail + editing
│   │   └── stats_screen.dart         # Posting stats
│   ├── services/
│   │   └── api_client.dart           # Dio + JWT interceptor
│   ├── models/
│   │   └── draft.dart                # Draft data model
│   ├── providers/
│   │   └── queue_provider.dart       # State management
│   └── widgets/                      # Shared UI components
│
├── android/
│   └── app/
│       └── src/
│           ├── main/                 # Shared Android resources
│           │   └── AndroidManifest.xml
│           ├── agencyA/              # Agency A flavor
│           │   ├── res/
│           │   │   ├── mipmap-hdpi/  # App icon (48×48)
│           │   │   ├── mipmap-xhdpi/ # App icon (96×96)
│           │   │   ├── mipmap-xxhdpi/# App icon (144×144)
│           │   │   └── values/
│           │   │       └── strings.xml  # <app_name>Agency A Poster</app_name>
│           │   └── AndroidManifest.xml  # Package name override
│           └── agencyB/              # Agency B flavor
│               ├── res/              # (same structure)
│               └── AndroidManifest.xml
│
├── ios/
│   └── Runner/
│       ├── Base/                     # Shared iOS resources
│       ├── AgencyA/                  # Agency A flavor
│       │   ├── Assets.xcassets/      # App icon set
│       │   ├── LaunchScreen.storyboard
│       │   └── Info.plist            # Bundle ID + display name
│       └── AgencyB/                  # Agency B flavor
│           ├── Assets.xcassets/
│           ├── LaunchScreen.storyboard
│           └── Info.plist
│
└── flavors/                          # Flavor configuration files
    ├── ramp_default.json             # RAMP internal (default)
    ├── agency_a.json                 # Agency A config
    └── agency_b.json                 # Agency B config
```

---

## 3. Flavor Configuration File

Each partner gets a JSON config file that defines their branding:

```json
{
  "flavorName": "agencyA",
  "appName": "RedditPro by AgencyA",
  "bundleId": "com.agencya.redditpro",
  "apiBaseUrl": "https://reddit.agencya.com/api",
  "colors": {
    "primary": "#1E40AF",
    "accent": "#F59E0B",
    "background": "#FFFFFF",
    "surface": "#F3F4F6"
  },
  "features": {
    "pushNotifications": true,
    "offlineMode": true,
    "biometricAuth": false
  },
  "fcmProjectId": "agencya-reddit-pro",
  "supportEmail": "support@agencya.com"
}
```

At runtime, the app reads this config and applies branding throughout the UI — no conditional logic per partner, just theme data.

---

## 4. Build Commands

```bash
# Android APK (for testing / sideloading)
flutter build apk --flavor=agencyA \
  --dart-define=API_URL=https://reddit.agencya.com/api \
  --dart-define=FLAVOR=agencyA

# Android App Bundle (for Play Store submission)
flutter build appbundle --flavor=agencyA \
  --dart-define=API_URL=https://reddit.agencya.com/api \
  --dart-define=FLAVOR=agencyA

# iOS (for App Store submission)
flutter build ios --flavor=agencyA \
  --dart-define=API_URL=https://reddit.agencya.com/api \
  --dart-define=FLAVOR=agencyA

# Run in development (hot reload with flavor)
flutter run --flavor=agencyA \
  --dart-define=API_URL=https://reddit.agencya.com/api \
  --dart-define=FLAVOR=agencyA
```

**One command = one branded app.** No code changes between builds.

---

## 5. What Changes Per Flavor

| Element | Where Configured | User-Visible Effect |
|---------|-----------------|---------------------|
| App name | `strings.xml` / `Info.plist` | Name on home screen ("RedditPro by AgencyA") |
| App icon | `mipmap-*/` / `Assets.xcassets/` | Launcher icon (partner's logo/brand) |
| Splash screen | `LaunchScreen.storyboard` / `launch_background.xml` | Loading screen (partner colors + logo) |
| Color scheme | `flavor_config.dart` via `--dart-define` | Primary, accent, background throughout app |
| API endpoint | `--dart-define=API_URL=...` | Points to partner's white-label domain |
| Bundle ID | `build.gradle` / `Info.plist` | Unique store listing (com.agencya.redditpro) |
| Package name | `AndroidManifest.xml` | Android package identifier |
| Push notifications | FCM project config | Partner's own Firebase project |
| Support email | Flavor config JSON | In-app "Contact Support" link |

---

## 6. What Stays Shared (95% of Code)

All of the following is written once and works identically across all partner apps:

| Component | Description |
|-----------|-------------|
| Login/Auth flow | JWT authentication against partner's API endpoint |
| Draft queue screen | Pull-to-refresh list of pending drafts |
| Draft detail screen | View thread context, edit comment, approve/reject |
| Posting workflow | One-tap post to Reddit (via backend proxy) |
| Offline support | SQLite queue for drafts when offline, sync on reconnect |
| Push notification handling | FCM listener (project ID varies, logic identical) |
| API client (Dio) | HTTP client with JWT interceptor, token refresh |
| Error handling | Retry logic, offline detection, user-friendly errors |
| Navigation | Bottom nav, screen routing, deep links |
| State management | Provider/Riverpod for queue state |

**The partner never sees or touches code.** They provide: logo, colors, domain. We produce: signed app binary.

---

## 7. CI/CD Pipeline (Automated Builds)

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions / Codemagic                 │
│                                                              │
│  Trigger: Push to main OR manual dispatch (partner name)     │
│                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ Read flavor │    │ Build APK + │    │ Upload to   │     │
│  │ config JSON │ →  │ IPA with    │ →  │ artifact    │     │
│  │             │    │ signing     │    │ storage     │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                                                              │
│  Matrix build: all flavors in parallel                       │
│  Output: signed APK + signed IPA per partner                │
└─────────────────────────────────────────────────────────────┘
```

**Workflow:**
1. Partner onboards → we create `flavors/partner_name.json` + asset folder
2. Push to repo triggers CI/CD
3. CI builds all flavors in parallel (matrix strategy)
4. Signed binaries uploaded to secure storage
5. Partner downloads and submits to their store listing

---

## 8. App Store Publishing Model

| Responsibility | Owner | Detail |
|---------------|-------|--------|
| Developer account | **Partner** | Apple $99/year, Google $25 one-time |
| App signing certificates | **Partner** | Generated in their developer portal |
| Build binary (APK/IPA) | **RAMP** | We build and sign with partner's certs |
| Store listing (screenshots, description) | **Partner** | Their brand, their copy |
| App review submission | **Partner** | They click "Submit for Review" |
| Updates | **RAMP builds** → **Partner submits** | Or CodePush/Shorebird for OTA where possible |

**Why partner owns the listing:**
- Their brand appears as the developer
- Their support email receives user inquiries
- No trace of RAMP in the store listing
- They control pricing (free app, or paid if they want)

---

## 9. Implementation Effort

| Task | Time | Dependency |
|------|------|-----------|
| Initial flavor infrastructure setup | 1 day | ramp_poster app exists |
| Android flavor configuration (Gradle) | 2 hours | — |
| iOS flavor configuration (Xcode schemes) | 2 hours | — |
| Runtime theme injection (FlavorConfig class) | 4 hours | — |
| CI/CD pipeline (GitHub Actions or Codemagic) | 1 day | Signing certs |
| Documentation for partner asset handoff | 2 hours | — |
| **Total first-time setup** | **3 days** | — |

**Per-partner addition (after initial setup):**

| Task | Time |
|------|------|
| Create flavor config JSON | 15 min |
| Add Android resources (icon, name) | 30 min |
| Add iOS resources (icon, launch screen) | 30 min |
| Test build (both platforms) | 30 min |
| Generate signed binaries | 30 min (CI does this) |
| **Total per new partner** | **2-4 hours** |

---

## 10. Technical Considerations

### Why Flutter (not React Native or native)

| Factor | Flutter | React Native | Native (Swift + Kotlin) |
|--------|---------|-------------|------------------------|
| Build flavors | Native support | Requires extra config | Native support |
| Single codebase | ✅ One Dart codebase | ✅ One JS codebase | ❌ Two codebases |
| Performance | Near-native (Skia) | Bridge overhead | Native |
| White-label builds | Trivial (--flavor flag) | Complex (env configs) | Trivial but 2x work |
| Hot reload | ✅ Sub-second | ✅ Fast refresh | ❌ Rebuild required |
| App size | ~15 MB | ~25 MB | ~8 MB |
| Our existing code | ✅ ramp_poster exists | Would need rewrite | Would need rewrite |

**Decision:** Flutter is already chosen and partially built. Flavor support is a native Flutter feature, not a hack.

### PWA Fallback

For partners who don't want App Store complexity:
- Same Flutter codebase compiles to web (`flutter build web`)
- Deployed as PWA on partner's domain
- Installable on home screen (Add to Home Screen prompt)
- No store submission required
- Trade-off: no push notifications on iOS, no offline support

---

## 11. Security & Isolation

| Concern | Mitigation |
|---------|-----------|
| API endpoint hardcoded | Injected at build time via `--dart-define`, not changeable at runtime |
| Partner A accessing Partner B's data | API enforces RBAC — app only sees what the JWT allows |
| Reverse engineering API URL | HTTPS + certificate pinning + JWT auth = URL alone is useless |
| Shared code vulnerability | One fix propagates to all flavors on next build |
| Signing key compromise | Each partner owns their own signing keys — isolated blast radius |

---

## 12. Summary for Investors

> "Mobile white-labeling is not a future feature — it's a configuration step. Flutter's build flavor system lets us produce a uniquely branded app for each partner in under 4 hours. The partner's avatar owners open the partner's app, see the partner's brand, and never know RAMP exists. This is the same architecture used by companies like BMW, Google Pay, and Alibaba for their multi-brand Flutter apps."

**Key numbers:**
- 95% shared code across all partner apps
- 2-4 hours to add a new partner's branded app
- $0 marginal infrastructure cost per app (same backend)
- Partner owns their store listing (complete brand separation)
- One security fix updates all partner apps simultaneously

---

*Document prepared for investor/partner technical due diligence. Implementation requires ramp_poster MVP to exist first (currently in development).*
