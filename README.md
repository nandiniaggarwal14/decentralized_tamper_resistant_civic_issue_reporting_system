# 🏛 Decentralized Tamper-Resistant Civic Issue Reporting System

A full-stack civic issue management platform that empowers citizens to report local problems, assigns them to the correct government wards and departments, and anchors every report's cryptographic fingerprint onto the **Ethereum Sepolia** testnet to prevent tampering. Media evidence (images, audio, video) is stored via a simulated **IPFS** layer and served locally.

---

## Table of Contents
1. [Overview](#overview)
2. [Tech Stack](#tech-stack)
3. [Architecture](#architecture)
4. [User Roles](#user-roles)
5. [Key Features](#key-features)
6. [Project Structure](#project-structure)
7. [Environment Variables](#environment-variables)
8. [Setup & Running Locally](#setup--running-locally)
9. [Database Schema Overview](#database-schema-overview)
10. [API Reference](#api-reference)
11. [Smart Contract](#smart-contract)
12. [Seeding & Data Reset](#seeding--data-reset)
13. [Running Tests](#running-tests)
14. [Priority System](#priority-system)

---

## Overview

Citizens submit civic issues (potholes, power outages, water leaks, etc.) with GPS coordinates, category, description, and optional media. The system:

- **Auto-routes** the issue to the correct **Ward** (based on GPS proximity) and **Department** (based on category).
- Computes a **SHA-256 hash** of the issue data and stores it both in the database and on the **Ethereum Sepolia** blockchain.
- Allows **upvoting** by citizens; upvotes drive a **dynamic priority ranking** visible to ward members and government authorities.
- Provides **role-based dashboards** so each stakeholder sees only what they need.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python) |
| Frontend | Vanilla HTML + CSS + JavaScript |
| Database | Neon PostgreSQL (cloud-hosted) |
| Blockchain | Ethereum Sepolia via Infura + Web3.py |
| Smart Contract | Solidity (Hardhat deployment) |
| Media Storage | Local filesystem (`uploads/`) + simulated IPFS CIDs |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Testing | pytest + httpx (TestClient) |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Browser (Frontend)                     │
│  index.html · citizen.html · ward.html · authority.html      │
│  admin.html · report.html                                     │
└───────────────────────┬──────────────────────────────────────┘
                        │ HTTP / REST
┌───────────────────────▼──────────────────────────────────────┐
│                  FastAPI Backend (main.py)                     │
│                                                               │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Auth      │  │  Routing     │  │  IPFS Service        │  │
│  │  (JWT)     │  │  (GPS+Cat)   │  │  (local simulation)  │  │
│  └────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │            Blockchain Service (Web3.py)                  │  │
│  │     store_issue_hash() / verify_issue_hash()             │  │
│  └──────────────────────────┬─────────────────────────────┘  │
└─────────────────────────────┼────────────────────────────────┘
                              │
              ┌───────────────▼───────────────┐
              │   Neon PostgreSQL (cloud)      │
              │   issues, users, wards,        │
              │   departments, votes,          │
              │   issue_status_history         │
              └───────────────────────────────┘
                              │
              ┌───────────────▼───────────────┐
              │   Ethereum Sepolia Testnet     │
              │   CivicRegistry.sol            │
              │   (SHA-256 hash anchoring)     │
              └───────────────────────────────┘
```

---

## User Roles

| Role | Description | Dashboard |
|---|---|---|
| **Citizen** | Registers, submits and tracks their own issues, upvotes issues | `citizen.html` |
| **Ward Member** | Manages issues routed to their ward, redirects to departments | `ward.html` |
| **Government Authority** | Manages issues in their department, marks in-progress or resolved | `authority.html` |
| **Admin** | Approves/rejects pending users, views all users and system stats | `admin.html` |

> Ward Members and Government Authorities require **Admin approval** before they can access their dashboards.

---

## Key Features

### Issue Lifecycle
```
Submitted (pending) → In Progress → Resolved
```
- Issues can no longer be `rejected` — this state has been removed to ensure accountability.

### Dynamic Priority (Upvote-Driven)
Issues are **automatically ranked by upvote count**. The priority badge on each card is assigned dynamically when fetching issues:

| Rank position | Priority Badge |
|---|---|
| Top 25% | 🔴 Critical |
| Next 25% | 🟠 High |
| Next 25% | 🟡 Medium |
| Bottom 25% | 🟢 Low |

Ward members can **no longer manually set priority** — it is fully driven by community upvotes.

### Upvote System
- Citizens upvote issues they care about (one upvote/downvote per user per issue).
- A 5-second cooldown prevents spam voting.
- Upvote count is visible on every card across all three role dashboards.

### Blockchain Integrity Verification
- Each issue gets a deterministic SHA-256 hash of its immutable fields.
- Hash is stored in the database and pushed to the Sepolia smart contract.
- Any user can verify tamper-resistance by clicking "Verify Integrity" on a citizen card.

### Auto-Routing
- **Ward**: Determined by GPS haversine distance to the nearest ward centre.
- **Department**: Determined by issue category via the `category_department_map` table.

### Multilingual Support
- English and Hindi (`frontend/src/lang/en.json`, `hi.json`)
- Language switcher in the top navigation bar.

---

## Project Structure

```
├── backend/
│   └── app/
│       ├── main.py                # All FastAPI routes & business logic
│       ├── auth.py                # JWT token creation & validation
│       ├── database.py            # Neon PostgreSQL connection pool
│       ├── schema.sql             # Full DB schema (run via init_db())
│       ├── seed.py                # Truncate + re-seed (admin only)
│       ├── routing.py             # GPS ward routing + category classification
│       ├── blockchain_service.py  # Web3.py Sepolia integration
│       ├── ipfs_service.py        # Simulated IPFS JSON storage
│       ├── backfill_hashes.py     # One-time script to hash existing issues
│       ├── verify_sync_status.py  # Checks DB vs on-chain hash consistency
│       ├── CivicRegistry.json     # Compiled ABI for the smart contract
│       ├── Verification.json      # Compiled ABI for the verification contract
│       └── tests/
│           ├── conftest.py
│           ├── test_admin.py
│           ├── test_auth.py
│           ├── test_issues.py
│           ├── test_routing.py
│           └── test_voting.py
├── frontend/
│   └── src/
│       ├── index.html             # Home page (Login / Register)
│       ├── citizen.html / .js     # Citizen dashboard
│       ├── ward.html / .js        # Ward member dashboard
│       ├── authority.html / .js   # Government authority dashboard
│       ├── admin.html / .js       # Admin dashboard
│       ├── report.html / .js      # Issue submission form
│       ├── auth.js                # Shared auth helpers
│       ├── i18n.js                # Internationalisation engine
│       ├── styles.css             # Global design system
│       └── lang/
│           ├── en.json
│           └── hi.json
├── smart_contract/
│   ├── contracts/
│   │   └── CivicRegistry.sol      # Solidity hash registry
│   ├── scripts/
│   │   └── deploy.js              # Hardhat deploy script
│   └── hardhat.config.js
├── database/
│   └── issues.json                # Sample data reference
├── uploads/                       # Uploaded media files (gitignored)
├── ipfs_storage/                  # Simulated IPFS JSON blobs
├── .env                           # Secrets (never commit)
├── requirements.txt
└── README.md
```

---

## Environment Variables

Create a `.env` file in the project root with the following:

```env
# PostgreSQL (Neon cloud or any PostgreSQL-compatible URL)
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require

# Ethereum Sepolia via Infura
INFURA_URL=https://sepolia.infura.io/v3/YOUR_PROJECT_ID
CONTRACT_ADDRESS=0xYourDeployedContractAddress
WALLET_PRIVATE_KEY=0xYourWalletPrivateKey
CHAIN_ID=11155111

# JWT Secret
SECRET_KEY=your_random_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

---

## Setup & Running Locally

### 1. Create and Activate Virtual Environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy or create `.env` with the variables listed above.

### 4. Initialise Database Schema

```bash
python -m backend.app.database
```

### 5. Seed the Database (Admin Only)

```bash
python -m backend.app.seed
```

This will:
- Truncate all tables.
- Insert 7 departments, 30 category-department mappings, 8 Delhi wards.
- Create the **admin** account: `admin` / `123456789`.

### 6. Start the Server

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

### 7. Open in Browser

```
http://127.0.0.1:8000
```

---

## Database Schema Overview

| Table | Purpose |
|---|---|
| `users` | All users (admin, citizen, ward_member, authority) |
| `wards` | Geographic ward boundaries with GPS centre + radius |
| `departments` | Government departments (Roads, Water, Electricity, etc.) |
| `category_department_map` | Maps issue categories to departments |
| `issues` | All civic issues with status, hash, media, location |
| `issue_votes` | Per-user upvote/downvote records |
| `issue_status_history` | Full audit trail of status changes |
| `failed_blockchain_txns` | Retry queue for failed Sepolia transactions |

---

## API Reference

### Auth
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register a new user |
| `POST` | `/api/auth/login` | Login and get JWT token |
| `GET` | `/api/auth/me` | Get current user profile |

### Issues (Public / Citizen)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/issues` | List all issues (sorted by upvotes) |
| `POST` | `/api/issues` | Submit a new civic issue |
| `POST` | `/api/issues/{id}/vote` | Cast an upvote or downvote |
| `GET` | `/api/issues/{id}/verify` | Verify tamper-resistance on-chain |

### Ward Member
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/ward/issues` | Issues routed to this ward |
| `POST` | `/api/ward/issues/{id}/redirect` | Redirect issue to a department |
| `GET` | `/api/ward/stats` | Ward-level statistics |
| `GET` | `/api/ward/profile` | Ward member's profile |
| `POST` | `/api/ward/profile` | Update ward member's profile |

### Government Authority
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/authority/issues` | Issues for this department |
| `PATCH` | `/api/authority/issues/{id}/status` | Update status (`pending`, `in_progress`, `resolved`) |
| `POST` | `/api/authority/issues/{id}/resolve` | Resolve with completion proof |

### Admin
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/admin/pending-users` | Users pending approval |
| `POST` | `/api/admin/approve-user/{id}` | Approve a user |
| `POST` | `/api/admin/reject-user/{id}` | Delete a pending user |
| `GET` | `/api/admin/stats` | System-wide statistics |
| `GET` | `/api/admin/users` | List all users |
| `GET` | `/api/admin/wards` | All wards with assigned members |
| `GET` | `/api/admin/departments` | All departments with staff |

---

## Smart Contract

The Solidity contract `CivicRegistry.sol` provides a tamper-proof hash registry.

### Deploy

```bash
cd smart_contract
npm install
# Create smart_contract/.env from .env.example
npx hardhat run scripts/deploy.js --network sepolia
```

Copy the deployed address into root `.env` as `CONTRACT_ADDRESS`.

---

## Seeding & Data Reset

To wipe all issues, votes, and users and start fresh (admin account recreated):

```bash
python -m backend.app.seed
```

To backfill SHA-256 hashes for existing issues that predate blockchain integration:

```bash
python -m backend.app.backfill_hashes
```

To check if all DB hashes match on-chain state:

```bash
python -m backend.app.verify_sync_status
```

---

## Running Tests

```bash
python -m pytest
```

All 24 unit tests cover admin operations, authentication, issue submission, ward routing, and voting.

---

## Priority System

Priority is **not set manually**. It is calculated dynamically each time issues are fetched, based on the rank of each issue in the upvote-sorted list:

```
Issues sorted by upvote_count DESC → assigned priority by percentile rank:
  Top 25%    → Critical 🔴
  25–50%     → High     🟠
  50–75%     → Medium   🟡
  Bottom 25% → Low      🟢
```

This ensures that community-driven issues always surface at the top with appropriate urgency.
