# Clinical Sovereignty Lab

## Little Nate — AI Therapy Platform

> *"A space for growth, reflection, and healing."*

---

## 🏛️ Overview

Little Nate is a comprehensive AI-powered therapy platform featuring:

- **Nate AI** — Conversational AI companion (text + voice)
- **Nevedal Engine** — Quantum emotional coherence tracking
- **Night School** — AI training and wisdom management
- **Coach Portal** — Tools for human therapists
- **Sovereign Command** — Admin console

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Git
- Azure OpenAI credentials

### 1. Clone & Configure

```bash
git clone git@github.com:Thera-cloud/Clinical-Sovereignty-Lab.git
cd Clinical-Sovereignty-Lab

# Copy environment template
cp .env.template .env

# Edit with your credentials
nano .env
```

### 2. Start Services

```bash
# Start everything
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f backend
```

### 3. Access

| Service | URL |
|---------|-----|
| API | http://10.0.0.81:8000 |
| Admin | http://10.0.0.81:3000 |
| WebSocket | ws://10.0.0.81:8765 |
| API Docs | http://10.0.0.81:8000/docs |

---

## 📁 Project Structure

```
Clinical-Sovereignty-Lab/
├── backend/                 # Python FastAPI + WebSocket
│   ├── app/
│   │   ├── main.py         # API entry point
│   │   ├── config.py       # Settings
│   │   ├── routers/        # API endpoints
│   │   ├── services/       # Business logic
│   │   │   ├── nevedal_engine.py
│   │   │   ├── night_school_director.py
│   │   │   └── stripe_integration.py
│   │   └── websocket/      # Real-time handlers
│   ├── migrations/         # Database schemas
│   └── tests/
│
├── mobile/                  # Flutter app
│   ├── lib/
│   │   ├── main.dart
│   │   ├── config/
│   │   ├── screens/
│   │   ├── viewmodels/
│   │   └── services/
│   └── pubspec.yaml
│
├── admin/                   # React admin console
│   └── src/
│       └── SovereignCommand.jsx
│
├── docker-compose.yml
├── .env.template
└── SETUP_GUIDE.md          # Detailed setup instructions
```

---

## 🔧 Configuration

All configuration is in `.env`. Key variables:

```bash
# Network
SERVER_HOST=10.0.0.81
WEBSOCKET_PORT=8765

# Azure OpenAI
AZURE_API_KEY=your_key
AZURE_OPENAI_ENDPOINT=your_endpoint
AZURE_OPENAI_DEPLOYMENT=gpt-realtime

# Database
POSTGRES_PASSWORD=your_password

# Feature Flags
ENABLE_NEVEDAL=true
ENABLE_STRIPE=false
```

See `SETUP_GUIDE.md` for complete configuration details.

---

## 🧬 Key Technologies

### Nevedal Formula

Quantum emotional coherence calculation:

```
C_emo(t) = [β · p_ent · T_tunnel] / [γ_env + E_G^(joint)/ℏ] × exp[-decay × t]
```

### Night School

AI training system with:
- PII detection & redaction
- Wisdom versioning
- Adversarial testing (The Dojo)

### Voice Biometrics

Extracts: pitch, energy, speech rate, pause ratio for emotional state inference.

---

## 💰 Pricing Tiers

| Tier | Price | Features |
|------|-------|----------|
| **Threshold** (Trial) | Free | 7 days, limited AI |
| **Inner Chamber** | $49/mo | Unlimited AI, voice mode |
| **Sovereign Circle** | $149/mo | Full platform, family linking, coaching |

---

## 📱 Mobile App

Build and run the Flutter app:

```bash
cd mobile
flutter pub get
flutter run
```

The app is pre-configured to connect to `10.0.0.81:8765`.

---

## 🛡️ Security

- JWT authentication
- PostgreSQL with encrypted connections
- PII detection and redaction
- HIPAA-compliant data handling
- Audit logging for all admin actions

---

## 📚 Documentation

- `SETUP_GUIDE.md` — Step-by-step setup
- `ANALYTICS_AND_CRISIS_PROTOCOL.md` — Event tracking & crisis handling
- `MVVM_INTEGRATION_GUIDE.md` — Architecture patterns
- API Docs: http://10.0.0.81:8000/docs

---

## 🤝 Contributing

1. Create a feature branch
2. Make changes
3. Run tests: `pytest backend/tests/ -v`
4. Submit PR

---

## 📄 License

Proprietary — Clinical Sovereignty Lab / Thera-cloud

---

*Built with care for those seeking growth and healing.*
