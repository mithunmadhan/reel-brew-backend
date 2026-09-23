# Creator Platform API

FastAPI backend.

## Setup

```bash
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
cp .env.example .env       # fill in secrets
```

Set `DATABASE_URL` in `.env` to a real PostgreSQL instance, and generate an
`ENCRYPTION_KEY` (used to encrypt `social_accounts.access_token` at rest):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Apply migrations, then start the API:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

## Structure

```
app/
  main.py            # FastAPI app entrypoint
  config.py          # Settings loaded from .env
  database.py        # SQLAlchemy engine/session, declarative Base
  core/
    encryption.py    # EncryptedString column type (Fernet)
  models/            # SQLAlchemy ORM models (users, creator_profiles, ...)
  routes/            # API route handlers
  services/          # Business logic
  langgraph_flows/   # LangGraph agent/flow definitions
alembic/             # Migration environment (env.py wired to app models/settings)
```

## Migrations

```bash
alembic revision --autogenerate -m "describe change"   # generate a new migration
alembic upgrade head                                    # apply migrations
alembic downgrade -1                                    # roll back one migration
```
