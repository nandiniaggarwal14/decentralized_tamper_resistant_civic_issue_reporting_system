# Decentralized Tamper-Resistant Civic Issue Reporting System

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
12. [Blockchain Integration Details](#blockchain-integration-details)
13. [Seeding & Data Reset](#seeding--data-reset)
14. [Running Tests](#running-tests)
15. [Priority System](#priority-system)
16. [Collaboration Guide](#collaboration-guide)

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
| Backend | FastAPI (Python 3.10+) |
| Frontend | Vanilla HTML + CSS + JavaScript |
| Database | Neon PostgreSQL (cloud-hosted, shared) |
| Blockchain | Ethereum Sepolia via Infura + Web3.py |
| Smart Contract | Solidity (Hardhat deployment) |
| Media Storage | Local filesystem (`uploads/`) + simulated IPFS CIDs |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Testing | pytest + httpx (TestClient) |

---

## Architecture

```
+--------------------------------------------------------------+
|                     Browser (Frontend)                        |
|  index.html - citizen.html - ward.html - authority.html      |
|  admin.html - report.html                                    |
+---------------------------+----------------------------------+
                            | HTTP / REST
+---------------------------v----------------------------------+
|                FastAPI Backend (main.py)                      |
|                                                              |
|  +----------+  +------------+  +------------------------+   |
|  | Auth     |  | Routing    |  | IPFS Service           |   |
|  | (JWT)    |  | (GPS+Cat)  |  | (local simulation)     |   |
|  +----------+  +------------+  +------------------------+   |
|                                                              |
|  +--------------------------------------------------------+  |
|  |         Blockchain Service (Web3.py)                    |  |
|  |  store_issue_hash() / verify_issue_hash()               |  |
|  |  EIP-1559 gas + async receipt tracking                  |  |
|  +------------------------+-------------------------------+  |
+---------------------------+----------------------------------+
                            |
            +---------------v-----------------+
            |   Neon PostgreSQL (cloud)        |
            |   issues, users, wards,          |
            |   departments, votes,            |
            |   issue_status_history,          |
            |   failed_blockchain_txns         |
            +---------------------------------+
                            |
            +---------------v-----------------+
            |   Ethereum Sepolia Testnet       |
            |   CivicRegistry.sol              |
            |   (SHA-256 hash anchoring)       |
            +---------------------------------+
```

---

## User Roles

| Role | Description | Dashboard |
|---|---|---|
| **Citizen** | Registers, submits and tracks their own issues, upvotes issues | `citizen.html` |
| **Ward Member** | Manages issues routed to their ward, redirects to departments | `ward.html` |
| **Government Authority** | Manages issues in their department, marks in-progress or resolved | `authority.html` |
| **Admin** | Approves/rejects pending users, views all users, system stats, blockchain monitoring | `admin.html` |

> Ward Members and Government Authorities require **Admin approval** before they can access their dashboards.

---

## Key Features

### Issue Lifecycle
```
Submitted (pending) --> In Progress --> Resolved
```
- Issues can no longer be `rejected` -- this state has been removed to ensure accountability.

### Dynamic Priority (Upvote-Driven)
Issues are **automatically ranked by upvote count**. The priority badge on each card is assigned dynamically when fetching issues:

| Rank position | Priority Badge |
|---|---|
| Top 25% | Critical |
| Next 25% | High |
| Next 25% | Medium |
| Bottom 25% | Low |

Ward members can **no longer manually set priority** -- it is fully driven by community upvotes.

### Upvote System
- Citizens upvote issues they care about (one upvote/downvote per user per issue).
- A 5-second cooldown prevents spam voting.
- Upvote count is visible on every card across all three role dashboards.

### Blockchain Integrity Verification
- Each issue gets a deterministic SHA-256 hash of its immutable fields.
- Hash is stored in the database and pushed to the Sepolia smart contract.
- Any user can verify tamper-resistance by clicking "Verify Integrity" on a citizen card.
- Transactions use **EIP-1559** gas estimation for fast confirmation on Sepolia.
- Receipt verification runs in a **background thread** so the API responds instantly.
- Failed transactions are queued in `failed_blockchain_txns` and can be retried from the admin panel.

### Auto-Routing
- **Ward**: Determined by GPS haversine distance to the nearest ward centre.
- **Department**: Determined by issue category via the `category_department_map` table.

### Multilingual Support
- English and Hindi (`frontend/src/lang/en.json`, `hi.json`)
- Language switcher in the top navigation bar.

---

## Project Structure

```
.
|-- backend/
|   |-- app/
|   |   |-- main.py                # FastAPI app entry point, middleware, static mounts
|   |   |-- config.py              # Centralised configuration constants
|   |   |-- auth.py                # JWT token creation & validation, password hashing
|   |   |-- database.py            # Neon PostgreSQL connection pool (psycopg2)
|   |   |-- schema.sql             # Full DB schema with migrations (run via init_db())
|   |   |-- models.py              # Pydantic request/response models
|   |   |-- helpers.py             # Shared utility functions (hashing, priority calc, etc.)
|   |   |-- routing.py             # GPS ward routing + category classification
|   |   |-- blockchain_service.py  # Web3.py Sepolia integration (EIP-1559, async receipts)
|   |   |-- ipfs_service.py        # Simulated IPFS JSON storage
|   |   |-- routes/
|   |   |   |-- __init__.py
|   |   |   |-- auth.py            # /api/auth/* endpoints
|   |   |   |-- issues.py          # /api/issues/* endpoints
|   |   |   |-- ward.py            # /api/ward/* endpoints
|   |   |   |-- authority.py       # /api/authority/* endpoints
|   |   |   |-- admin.py           # /api/admin/* endpoints
|   |   |   |-- pages.py           # Static page serving (FileResponse mappings)
|   |   |-- abis/                  # Compiled contract ABIs (CivicRegistry.json)
|   |   |-- tests/
|   |   |   |-- conftest.py
|   |   |   |-- test_admin.py
|   |   |   |-- test_auth.py
|   |   |   |-- test_issues.py
|   |   |   |-- test_routing.py
|   |   |   |-- test_voting.py
|   |-- scripts/
|   |   |-- seed.py                # Truncate + re-seed (admin, wards, departments)
|   |   |-- backfill_hashes.py     # One-time script to hash existing issues
|   |   |-- verify_sync_status.py  # Checks DB vs on-chain hash consistency
|   |   |-- reset_passwords.py     # Password reset utility
|-- frontend/
|   |-- src/
|   |   |-- index.html             # Home page (Login / Register)
|   |   |-- citizen.html / .js     # Citizen dashboard
|   |   |-- ward.html / .js        # Ward member dashboard
|   |   |-- authority.html / .js   # Government authority dashboard
|   |   |-- admin.html / .js       # Admin dashboard (users, stats, blockchain monitor)
|   |   |-- report.html / .js      # Issue submission form
|   |   |-- auth.js                # Shared auth helpers
|   |   |-- i18n.js                # Internationalisation engine
|   |   |-- styles.css             # Global dark-mode design system
|   |   |-- lang/
|   |   |   |-- en.json
|   |   |   |-- hi.json
|-- smart_contract/
|   |-- contracts/
|   |   |-- CivicRegistry.sol      # Solidity hash registry
|   |-- scripts/
|   |   |-- deploy.js              # Hardhat deploy script
|   |-- hardhat.config.js
|-- uploads/                       # Uploaded media files (gitignored)
|-- ipfs_storage/                  # Simulated IPFS JSON blobs (gitignored)
|-- .env                           # Secrets (never committed)
|-- .gitignore
|-- requirements.txt
|-- HANDOVER.md                    # Developer handover document
|-- README.md
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

> **Important**: Both developers share the same `.env` values for `DATABASE_URL`, `INFURA_URL`, `CONTRACT_ADDRESS`, `WALLET_PRIVATE_KEY`, and `CHAIN_ID` since both connect to the same Neon database and the same Sepolia contract. Only share `.env` values securely and never commit the file to Git.

---

## Setup & Running Locally

### 1. Clone the Repository

```bash
git clone https://github.com/NandiniAggarwal14/Decentralized_Tamper_Resistant_Civic_Issue_Reporting_System.git
cd Decentralized_Tamper_Resistant_Civic_Issue_Reporting_System
```

### 2. Create and Activate Virtual Environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

> **Note on bcrypt**: `requirements.txt` pins `bcrypt==3.2.2` because `passlib 1.7.4` is incompatible with `bcrypt >= 4.0.0`. The newer bcrypt changed its API, which causes `passlib.verify()` to silently return `False` for correct passwords. Do not upgrade bcrypt without also upgrading passlib.

### 4. Configure Environment

Copy the `.env` template above into the project root and fill in the values. If you are the second developer (Nandini), request the shared `.env` values from the first developer.

### 5. Initialise Database Schema

```bash
python -m backend.app.database
```

This creates all tables and runs migration queries (e.g. adding new columns to existing tables) safely using `IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS`.

### 6. Seed the Database

```bash
python -m backend.scripts.seed
```

This will:
- Truncate all tables.
- Insert 7 departments, 30 category-department mappings, 8 Delhi wards.
- Create the **admin** account: `admin` / `123456789`.

### 7. Start the Server

```bash
python -m backend.app.main
```

Or equivalently:

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

### 8. Open in Browser

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
| `issue_status_history` | Full audit trail of status changes (with ipfs_cid & blockchain_hash) |
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
| `DELETE` | `/api/admin/users/{id}` | Delete a user |
| `GET` | `/api/admin/wards` | All wards with assigned members |
| `GET` | `/api/admin/departments` | All departments with staff |
| `GET` | `/api/admin/failed-transactions` | Failed blockchain transaction queue |
| `POST` | `/api/admin/retry-transactions` | Retry all failed transactions |

### Health
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | System health check (includes blockchain status) |

---

## Smart Contract

The Solidity contract `CivicRegistry.sol` provides a tamper-proof hash registry on Ethereum Sepolia.

### Contract Functions
| Function | Description |
|---|---|
| `storeIssueHash(uint256, string)` | Store an issue's SHA-256 hash on-chain |
| `getIssueHash(uint256)` | Retrieve a stored issue hash |
| `storeCompletionHash(uint256, string)` | Store a resolution proof hash |
| `getCompletionHash(uint256)` | Retrieve a completion hash |
| `storePersonnelHash(uint256, string)` | Store a personnel verification hash |
| `getPersonnelHash(uint256)` | Retrieve a personnel hash |

### Deploy

```bash
cd smart_contract
npm install
npx hardhat run scripts/deploy.js --network sepolia
```

Copy the deployed address into root `.env` as `CONTRACT_ADDRESS`.

### Current Deployment
- **Network**: Sepolia (Chain ID: 11155111)
- **Contract**: `0x569486209dF1AcF3033A8D6E7e6D745FF5e13483`
- **Wallet**: `0x91Ab709a669c8B7FD14e0972935a41bAb06fB147`

---

## Blockchain Integration Details

### EIP-1559 Gas Estimation
All blockchain transactions use EIP-1559 dynamic fee estimation:
- Fetches the latest block's `baseFeePerGas`
- Queries `eth.max_priority_fee` from the node
- Sets `maxFeePerGas = baseFee * 2 + priorityFee`
- Falls back to legacy `gasPrice` if EIP-1559 fields are unavailable

### Non-Blocking Transaction Flow
1. The API endpoint broadcasts the signed transaction and immediately returns the `tx_hash` to the user (sub-second response).
2. A background daemon thread polls for the transaction receipt (up to 180 seconds).
3. If the receipt shows `status == 0` (reverted) or the wait times out, the transaction is logged to the `failed_blockchain_txns` database table.
4. The admin can retry all failed transactions from the dashboard.

### Nonce Management
Transaction nonces are fetched with the `'pending'` block tag to account for in-flight transactions, preventing `nonce too low` and `replacement transaction underpriced` errors during rapid consecutive submissions.

---

## Seeding & Data Reset

To wipe all issues, votes, and users and start fresh (admin account recreated):

```bash
python -m backend.scripts.seed
```

To backfill SHA-256 hashes for existing issues that predate blockchain integration:

```bash
python -m backend.scripts.backfill_hashes
```

To check if all DB hashes match on-chain state:

```bash
python -m backend.scripts.verify_sync_status
```

---

## Running Tests

```bash
python -m pytest
```

All 24 unit tests cover admin operations, authentication, issue submission, ward routing, and voting. Tests use mock database connections and do not require a live Neon database or blockchain node.

| Test File | Coverage |
|---|---|
| `test_admin.py` | Admin-only endpoints, user approval/rejection, stats |
| `test_auth.py` | Register, login, token validation, role enforcement |
| `test_issues.py` | Issue submission, validation, public feed |
| `test_routing.py` | GPS ward detection, category-to-department mapping |
| `test_voting.py` | Upvote/downvote toggle, cooldown rate limiting |

---

## Priority System

Priority is **not set manually**. It is calculated dynamically each time issues are fetched, based on the rank of each issue in the upvote-sorted list:

```
Issues sorted by upvote_count DESC --> assigned priority by percentile rank:
  Top 25%    --> Critical
  25-50%     --> High
  50-75%     --> Medium
  Bottom 25% --> Low
```

This ensures that community-driven issues always surface at the top with appropriate urgency.

---

## Collaboration Guide

### For Nandini (or any collaborator pulling this branch)

1. **Pull the branch**:
   ```bash
   git pull origin main
   ```

2. **Install/update dependencies** (bcrypt version is critical):
   ```bash
   pip install -r requirements.txt
   ```

3. **Run database migrations** (safe to re-run, uses `IF NOT EXISTS`):
   ```bash
   python -m backend.app.database
   ```

4. **Seed if needed** (only if starting fresh):
   ```bash
   python -m backend.scripts.seed
   ```

5. **Verify `.env`**: Ensure your `.env` has all the required keys listed in the [Environment Variables](#environment-variables) section. Both developers share the same Neon DB and Sepolia contract.

6. **Start the server**:
   ```bash
   python -m backend.app.main
   ```

7. **Run tests** to confirm everything works:
   ```bash
   python -m pytest
   ```

> **Note**: The `ipfs_storage/` and `uploads/` directories are gitignored. They will be created automatically at runtime when issues are submitted. You do not need to manually create them.
