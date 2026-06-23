# 🤝 Project Handover Document
## Decentralized Tamper-Resistant Civic Issue Reporting System

> This document is intended for any developer or AI agent picking up this project. It covers the current state of the system, architectural decisions, known quirks, and a map of where everything lives.

---

## 1. What This Project Is

A civic issue reporting platform where:
- **Citizens** submit issues (potholes, power cuts, water leaks, etc.) with GPS location and evidence.
- The backend **auto-routes** each issue to the correct **ward** (by GPS distance) and **government department** (by category).
- Each issue is **cryptographically hashed (SHA-256)** and the hash is **anchored on the Ethereum Sepolia testnet** to create a tamper-proof audit trail.
- **Upvotes** by citizens determine the **priority ranking** of issues — fully automated, no manual priority setting.
- Role-based dashboards allow ward members and authorities to track and action issues.
- An admin dashboard handles user approval and system monitoring.

---

## 2. Repository Layout

```
root/
├── backend/app/
│   ├── main.py                ← ALL route handlers and business logic (~2250 lines)
│   ├── auth.py                ← JWT creation, validation, role-based dependency injection
│   ├── database.py            ← Neon PostgreSQL threaded connection pool (psycopg2)
│   ├── schema.sql             ← Full DB schema; run via init_db() in database.py
│   ├── seed.py                ← Wipe + re-seed: 7 depts, 8 wards, admin user only
│   ├── routing.py             ← GPS haversine ward finder + category classifier
│   ├── blockchain_service.py  ← Web3.py: store/verify SHA-256 hashes on Sepolia
│   ├── ipfs_service.py        ← Simulated IPFS: writes JSON blobs locally
│   ├── backfill_hashes.py     ← One-time script to hash pre-blockchain issues
│   ├── verify_sync_status.py  ← Compares DB hashes vs on-chain hashes
│   ├── CivicRegistry.json     ← ABI for the deployed Solidity contract
│   └── tests/                 ← 24 unit tests (mock DB, no live DB needed)
│
├── frontend/src/
│   ├── index.html             ← Login / Register page (centered, no stats cards)
│   ├── citizen.html/.js       ← Issue feed, upvoting, hash verification
│   ├── ward.html/.js          ← Ward issues, department redirect (no priority selector)
│   ├── authority.html/.js     ← Dept queue, mark in-progress / resolve (no reject button)
│   ├── admin.html/.js         ← User management, system stats
│   ├── report.html/.js        ← Issue submission form with GPS, media upload
│   ├── auth.js                ← Shared: login, register, token storage, redirects
│   ├── i18n.js                ← Translation engine (en/hi)
│   ├── styles.css             ← Global dark-mode design system
│   └── lang/en.json, hi.json
│
├── smart_contract/            ← Hardhat project for Solidity contract
├── uploads/                   ← Uploaded images/audio/video (served at /uploads/)
├── ipfs_storage/              ← Simulated IPFS JSON blobs
├── .env                       ← Secrets (see section 4)
├── requirements.txt           ← Python dependencies (categorized)
├── README.md                  ← Full project documentation
└── HANDOVER.md                ← This file
```

---

## 3. How the System Works End-to-End

### Issue Submission Flow
```
1. Citizen fills report.html form (title, description, category, GPS, media)
2. POST /api/issues (multipart form)
3. Backend:
   a. Saves media files to /uploads/
   b. Simulates IPFS storage → generates local CID
   c. GPS → routing_service.find_nearest_ward() → assigns ward_id
   d. Category → routing_service.classify_issue() → assigns department_id
   e. Computes SHA-256 hash of immutable fields
   f. Pushes hash to Ethereum Sepolia via blockchain_service.store_issue_hash()
   g. Inserts issue record into PostgreSQL (status='pending', priority='low')
```

### Priority Assignment Flow
```
1. Any GET /api/issues, /api/ward/issues, /api/authority/issues
2. Backend queries DB: ORDER BY upvote_count DESC, created_at DESC
3. Python function _assign_dynamic_priorities() applies percentile-based labels:
   - Top 25%    → 'critical'
   - 25–50%     → 'high'
   - 50–75%     → 'medium'
   - Bottom 25% → 'low'
4. Priority field in response is OVERWRITTEN by this function (DB value is ignored)
```

> ⚠️ **Important**: The `priority` column in the database is vestigial for the list endpoints. Dynamic priority is always computed in Python at response time. The DB column is still written at creation time as `'low'`.

### Voting Flow
```
1. POST /api/issues/{id}/vote with {"vote_type": "up"/"down"}
2. Upsert into issue_votes (toggle logic: same vote removes it)
3. Recompute upvote_count and downvote_count on the issues row
4. 5-second cooldown enforced via DB query on voter's last vote timestamp
```

### Blockchain Verification Flow
```
1. GET /api/issues/{id}/verify (citizen "Verify Integrity" button)
2. Backend recomputes SHA-256 hash from DB fields
3. Queries Sepolia contract for stored hash
4. Returns: verified=True if they match, tampered=True if they don't
```

---

## 4. Environment Variables Required

File: `.env` in project root.

```env
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
INFURA_URL=https://sepolia.infura.io/v3/YOUR_KEY
CONTRACT_ADDRESS=0xYourContractAddress
WALLET_PRIVATE_KEY=0xYourPrivateKey
CHAIN_ID=11155111
SECRET_KEY=any_random_string_at_least_32_chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

---

## 5. Key Design Decisions & Why

| Decision | Rationale |
|---|---|
| Priority is dynamic, not stored | Ensures ordering is always fair and reflects current upvote state without DB update on every vote |
| Rejection removed from authority | Accountability requirement: issues must be actioned, not dismissed |
| Manual priority removed from ward | Community votes should determine urgency, not individual officials |
| GPS haversine routing | Deterministic, no external API needed |
| Simulated IPFS locally | No Pinata/IPFS node required for dev/demo; CIDs are generated but files are local |
| Neon PostgreSQL | Serverless-friendly, free tier sufficient for dev; may cold-start → seed script retries expected |
| JWT in localStorage | Simple for demo; production would use httpOnly cookies |
| bcrypt password hashing | Standard; passlib[bcrypt] handles salt automatically |

---

## 6. Known Quirks & Gotchas

### Neon Database Cold Starts
Neon PostgreSQL pauses after inactivity. The first query after a pause will fail with a connection error. The connection pool in `database.py` has retry logic, but the `seed.py` script may fail on the first attempt if the database was sleeping. **Just re-run it.**

### Blockchain in Mock Mode
If `INFURA_URL` or `CONTRACT_ADDRESS` are missing/invalid, `blockchain_service.py` falls back to a mock mode that logs a warning but does not crash the server. Issues are still stored in the DB; verification will return `blockchain_unavailable`.

### IPFS is Simulated
`ipfs_service.py` does NOT talk to a real IPFS node. It writes JSON files to `ipfs_storage/` and returns a deterministic fake CID. This is intentional for demo purposes.

### Auth Guards
- `get_current_user` → requires valid JWT (any role)
- `RoleChecker(["ward_member"])` → JWT + role enforcement
- `get_optional_current_user` → used on public endpoints; returns None if no token

### Admin Credentials (Default After Seed)
```
Username: admin
Password: 123456789
```

---

## 7. Database Tables Quick Reference

```sql
users              → id, username, password_hash, role, full_name, contact, is_approved, ward_id, department_id
wards              → id, name, center_latitude, center_longitude, radius_meters, ward_member_id
departments        → id, name, description
category_dept_map  → category (PK), department_id
issues             → id, title, description, category, area, address, lat, lng, reporter_name, contact,
                     image_url, hash, status, priority, ipfs_cid, media_urls, upvote_count, downvote_count,
                     user_id, ward_id, department_id, completion_proof_ipfs_cid, completion_hash, created_at
issue_votes        → (issue_id, voter_id) PK, vote_type, created_at, updated_at
issue_status_hist  → id, issue_id, old_status, new_status, changed_by, comments, proof_url, created_at
failed_blockchain  → id, issue_id, issue_hash, error_message, retry_count, created_at
```

---

## 8. Running the Project

```bash
# 1. Activate venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Initialise DB schema (first time only)
python -m backend.app.database

# 4. Seed admin + reference data
python -m backend.app.seed

# 5. Start the server
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

# 6. Run tests
python -m pytest
```

---

## 9. Test Coverage Summary

| Test File | What it Tests |
|---|---|
| `test_admin.py` | Admin-only endpoints, user approval/rejection, stats |
| `test_auth.py` | Register, login, token validation, role enforcement |
| `test_issues.py` | Issue submission, validation, rate limiting, public feed |
| `test_routing.py` | GPS ward detection, category-to-department mapping |
| `test_voting.py` | Upvote/downvote toggle, cooldown rate limiting |

All 24 tests use a mock DB (no live Neon connection needed for tests).

---

## 10. Frontend Page Map

| URL | File | Role |
|---|---|---|
| `/` | `index.html` | Public — Login/Register |
| `/report` | `report.html` | Citizen — Submit issue |
| `/citizen` | `citizen.html` | Citizen — View feed, vote |
| `/ward` | `ward.html` | Ward Member — Manage ward issues |
| `/authority` | `authority.html` | Authority — Manage dept issues |
| `/admin` | `admin.html` | Admin — User management |

All pages check for a valid JWT on load and redirect to `/` if the token is missing or the role doesn't match.

---

## 11. What Is NOT Implemented (Out of Scope for Current Version)

- Real IPFS node integration (Pinata or local IPFS daemon)
- Email/SMS notifications
- Push notifications for status changes
- Map-based issue visualisation
- Public issue feed visible to non-logged-in users
- Production deployment configuration (Docker, Nginx, HTTPS)
- Password reset flow
- Pagination on issue lists

---

## 12. Suggested Next Steps

1. **Paginate issue lists** — large datasets will slow down `/api/issues` without LIMIT/OFFSET.
2. **Replace simulated IPFS** with Pinata API calls for true decentralised storage.
3. **Add map view** to citizen dashboard (Leaflet.js + Neon PostGIS or computed GPS).
4. **Email notifications** when issue status changes (SendGrid or SMTP).
5. **Dockerise** the backend for easy cloud deployment.
6. **Rate limit** the registration endpoint to prevent account farming.
