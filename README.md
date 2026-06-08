<div align="center">

# 📧 Gmail RAG Assistant

### An end-to-end AI pipeline that reads your Gmail and answers questions about it

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com)
[![Google OAuth](https://img.shields.io/badge/Google-OAuth2-EA4335?style=for-the-badge&logo=google&logoColor=white)](https://developers.google.com/identity)
[![License](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

> Authenticate with Google → sync your Gmail → ask AI questions about your emails — with full source citations.

[Features](#-features) · [Architecture](#-architecture) · [Tech Stack](#-tech-stack) · [Getting Started](#-getting-started) · [API Reference](#-api-reference) · [Roadmap](#-roadmap)

</div>

---

## 🎯 What This Project Does

Gmail RAG Assistant is a **production-grade Retrieval-Augmented Generation (RAG) pipeline** built on top of the Gmail API. It:

1. **Authenticates** users securely via Google OAuth 2.0
2. **Ingests** Gmail messages into a PostgreSQL database
3. **Chunks** email text into semantic segments using tiktoken
4. **Embeds** chunks using OpenAI `text-embedding-3-small` *(Phase 6)*
5. **Answers** natural language questions about your emails with GPT-4o and cited sources *(Phase 7)*
6. **Displays** results in a Next.js chat interface *(Phase 8)*

**Validated end-to-end:** 50 real Gmail emails → 381 searchable chunks in a single sync run.

---

## ✅ Build Status

| Phase | Feature | Status |
|:---:|---|:---:|
| 0 | Project scaffolding & monorepo structure | ✅ |
| 1 | FastAPI app · async PostgreSQL · `/health` endpoint | ✅ |
| 2 | SQLAlchemy ORM models · Alembic migrations | ✅ |
| 3 | Google OAuth 2.0 · JWT HttpOnly cookies · Fernet token encryption | ✅ |
| 4 | Gmail API integration · email ingestion · duplicate prevention · sync jobs | ✅ |
| 5 | Token-based chunking pipeline (tiktoken cl100k_base) | ✅ |
| 6 | OpenAI embeddings · pgvector similarity search | 🔄 In Progress |
| 7 | RAG query pipeline · GPT-4o answers · source citations | 📋 Planned |
| 8 | Next.js chat UI · email list · sync dashboard | 📋 Planned |

---

## ⚡ Features

### 🔐 Security-First Authentication
- Google OAuth 2.0 with signed CSRF state parameter
- JWT stored in **HttpOnly cookie** (not accessible via JavaScript)
- Google tokens **encrypted at rest** using Fernet symmetric encryption
- Scope validation ensures Gmail read permission is explicitly granted
- Redirect URL allowlist prevents open redirect attacks

### 📬 Gmail Ingestion Pipeline
- Full Gmail API v1 integration with automatic token refresh
- Exponential backoff on 429 rate limit responses
- **Duplicate prevention** via unique constraint on `gmail_message_id`
- Sync job tracking with status, progress counters, and error reporting
- Plaintext body extraction (skips HTML parts)

### ✂️ Semantic Chunking
- Token-based splitting using **tiktoken `cl100k_base`** encoder
- Configurable chunk size (default: 500 tokens) and overlap (default: 100 tokens)
- Subject + sender + body combined into searchable text per chunk
- `indexed_at` timestamp set after successful chunking

### 🗄️ Database Design
- Async SQLAlchemy with `asyncpg` driver
- Full Alembic migration history
- pgvector extension for embedding storage *(Phase 6)*
- Cascade deletes for GDPR compliance

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Browser / Client                    │
└──────────────────┬──────────────────────────────────────┘
                   │  HTTP + HttpOnly JWT Cookie
┌──────────────────▼──────────────────────────────────────┐
│                   FastAPI Backend                        │
│                                                          │
│  /auth/google/login       OAuth redirect                 │
│  /auth/google/callback    Token exchange + JWT           │
│  /sync/trigger            Gmail ingestion pipeline       │
│  /sync/status/{job_id}    Job progress polling           │
│  /emails                  Email listing        (Phase 6) │
│  /query                   RAG Q&A              (Phase 7) │
└──────┬──────────────────────────────┬───────────────────┘
       │                              │
┌──────▼──────┐              ┌────────▼────────┐
│  Gmail API  │              │  PostgreSQL 18   │
│  (Google)   │              │                  │
│             │              │  ┌─────────────┐ │
│  messages   │              │  │   users     │ │
│  threads    │              │  │   emails    │ │
│  profile    │              │  │   chunks    │ │
└─────────────┘              │  │   sync_jobs │ │
                             │  └─────────────┘ │
┌─────────────┐              │  ┌─────────────┐ │
│  OpenAI API │              │  │  pgvector   │ │
│             │◄─────────────┤  │  (Phase 6)  │ │
│  embeddings │              │  └─────────────┘ │
│  GPT-4o     │              └──────────────────┘
└─────────────┘
```

---

## 🛠️ Tech Stack

| Category | Technology | Purpose |
|---|---|---|
| **API Framework** | FastAPI (async) | High-performance REST API |
| **Database** | PostgreSQL 18 | Primary data store |
| **Vector Store** | pgvector | Embedding similarity search |
| **ORM** | SQLAlchemy (async) | Database abstraction |
| **Migrations** | Alembic | Schema version control |
| **Auth** | Google OAuth 2.0 | User authentication |
| **Sessions** | JWT + HttpOnly cookie | Secure session management |
| **Encryption** | Fernet (cryptography) | Token encryption at rest |
| **Gmail** | Gmail API v1 | Email ingestion |
| **Chunking** | tiktoken cl100k_base | Token-based text splitting |
| **Embeddings** | OpenAI text-embedding-3-small | Semantic vectors *(Phase 6)* |
| **LLM** | OpenAI GPT-4o | RAG answers *(Phase 7)* |
| **Frontend** | Next.js 14 + TypeScript | Chat UI *(Phase 8)* |
| **Task Queue** | Celery + Redis | Async ingestion *(Phase 8)* |
| **HTTP Client** | httpx (async) | External API calls |
| **Validation** | Pydantic v2 | Request/response schemas |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL 18
- Google Cloud project with **Gmail API enabled**
- OAuth 2.0 credentials (**Web application** type)

### 1. Clone & Install

```bash
git clone https://github.com/makadiyavatsall/ai-knowledge-engine.git
cd ai-knowledge-engine/backend

python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

### 2. Configure Environment

```bash
copy .env.example .env   # Windows
cp .env.example .env     # macOS/Linux
```

Edit `.env` with your values:

| Variable | How to Get It |
|---|---|
| `GOOGLE_CLIENT_ID` | Google Cloud Console → APIs & Services → Credentials |
| `GOOGLE_CLIENT_SECRET` | Same as above |
| `JWT_SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `TOKEN_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DATABASE_URL` | `postgresql+asyncpg://user:password@localhost:5432/gmail_rag` |

### 3. Run Migrations & Start

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### 4. Verify

```bash
# Health check
curl http://localhost:8000/health
# {"status":"ok","app":"Gmail RAG API"}

# Open in browser to authenticate
http://localhost:8000/auth/google/login

# Trigger Gmail sync
curl -X POST http://localhost:8000/sync/trigger \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
# {"status":"completed","total_messages":50,"total_chunks":381}
```

---

## 📡 API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | None | API health check |
| `GET` | `/auth/google/login` | None | Redirect to Google OAuth |
| `GET` | `/auth/google/callback` | None | OAuth callback, issues JWT |
| `GET` | `/sync/gmail/profile` | JWT | Gmail mailbox profile |
| `POST` | `/sync/trigger` | JWT | Run Gmail ingestion |
| `GET` | `/sync/status/{job_id}` | JWT | Poll sync job status |
| `GET` | `/emails` | JWT | List stored emails *(Phase 6)* |
| `POST` | `/query` | JWT | RAG question answering *(Phase 7)* |

---

## 🗂️ Project Structure

```
gmail-rag/
├── backend/
│   ├── app/
│   │   ├── api/                  # Route handlers
│   │   │   ├── auth.py           # OAuth login/callback
│   │   │   ├── sync.py           # Gmail sync endpoints
│   │   │   ├── emails.py         # Email listing (Phase 6)
│   │   │   └── query.py          # RAG query (Phase 7)
│   │   ├── core/
│   │   │   ├── config.py         # Pydantic-settings configuration
│   │   │   ├── database.py       # Async SQLAlchemy engine
│   │   │   └── security.py       # JWT, OAuth state, encryption
│   │   ├── models/
│   │   │   ├── user.py           # User + encrypted OAuth tokens
│   │   │   ├── email.py          # Gmail message storage
│   │   │   ├── chunk.py          # Text chunks + embeddings
│   │   │   └── sync_job.py       # Ingestion job tracking
│   │   ├── services/
│   │   │   ├── google_oauth.py   # OAuth flow + user upsert
│   │   │   ├── gmail.py          # Gmail API client
│   │   │   ├── ingestion.py      # End-to-end sync pipeline
│   │   │   ├── chunker.py        # Token-based text splitting
│   │   │   ├── embedder.py       # OpenAI embeddings (Phase 6)
│   │   │   └── rag.py            # RAG pipeline (Phase 7)
│   │   └── tasks/
│   │       └── celery_app.py     # Async workers (Phase 8)
│   ├── alembic/                  # Database migrations
│   ├── tests/                    # Test suite (Phase 8)
│   ├── .env.example              # Environment template
│   └── requirements.txt
├── frontend/                     # Next.js app (Phase 8)
│   └── src/
│       ├── components/
│       │   ├── ChatWindow.tsx
│       │   ├── EmailList.tsx
│       │   └── SyncStatus.tsx
│       └── lib/
├── infra/
│   ├── docker-compose.yml        # Full stack deployment
│   └── nginx.conf                # Reverse proxy config
└── README.md
```

---

## 🔒 Security Design

```
Google OAuth Token  →  Fernet encrypt  →  Store in PostgreSQL
                                          (never stored in plaintext)

User Session  →  JWT (HS256)  →  HttpOnly cookie
                                 (inaccessible to JavaScript)

OAuth State  →  URLSafeTimedSerializer  →  10-minute expiry
                                           (CSRF protection)
```

- Separate keys for JWT signing and token encryption (never reused)
- `AUTH_COOKIE_SECURE=true` enforced in production
- Redirect URL allowlist prevents open redirect attacks
- Gmail scope validation on every OAuth callback

---

## 📋 Roadmap

- [x] Google OAuth 2.0 authentication
- [x] Gmail API integration
- [x] Email ingestion with duplicate prevention
- [x] Token-based chunking pipeline
- [ ] OpenAI `text-embedding-3-small` embeddings
- [ ] pgvector cosine similarity search
- [ ] GPT-4o RAG answers with source citations
- [ ] Next.js chat interface
- [ ] Celery + Redis async ingestion
- [ ] Incremental Gmail sync via `historyId`
- [ ] Docker Compose production stack
- [ ] GDPR data deletion endpoint (`DELETE /user/data`)
- [ ] Automated test suite

---

## 👨‍💻 Author

**Vatsal Makadiya**

[![GitHub](https://img.shields.io/badge/GitHub-makadiyavatsall-181717?style=flat&logo=github)](https://github.com/makadiyavatsall)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0A66C2?style=flat&logo=linkedin)](https://www.linkedin.com/in/vatsal-makadiya-149476242/)
---

<div align="center">

Built with ❤️ using FastAPI · PostgreSQL · OpenAI · Gmail API

⭐ Star this repo if you find it useful!

</div>

