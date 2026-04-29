# Decentralized Tamper-Resistant Civic Issue Reporting System

Basic full-stack MVP with:
- Backend: FastAPI
- Frontend: HTML, CSS, JavaScript
- Storage: Neon PostgreSQL via `DATABASE_URL` in `.env`
- Integrity layer: Ethereum Sepolia via Infura + Solidity hash registry

## Features
- Submit civic issue with:
  - title
  - description
  - category
  - area
  - address
  - latitude/longitude
  - reporter name/contact
  - optional image
- Save uploaded images in `uploads/`
- Save issue records in Neon PostgreSQL table `issues`
- View submitted issues on the same page
- Store SHA-256 issue hash in Neon and on Sepolia testnet
- Verify issue integrity from dashboard using on-chain hash comparison

## Blockchain Setup (Sepolia + Infura)
1. Create an Infura endpoint for Sepolia.
2. Create/fund a wallet with Sepolia ETH.
3. Deploy `smart_contract/contracts/Verification.sol` to Sepolia.
4. Copy the deployed contract address.
5. Add these variables to root `.env`:
   - `DATABASE_URL=your_neon_postgres_connection_string`
   - `INFURA_URL=https://sepolia.infura.io/v3/your_project_id`
   - `CONTRACT_ADDRESS=0xYourDeployedContractAddress`
   - `WALLET_PRIVATE_KEY=your_wallet_private_key`
   - `CHAIN_ID=11155111`

## Run
1. Create and activate virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Create `.env` in project root and add:
   - `DATABASE_URL=your_neon_postgres_connection_string`
   - `INFURA_URL=https://sepolia.infura.io/v3/your_project_id`
   - `CONTRACT_ADDRESS=0xYourDeployedContractAddress`
   - `WALLET_PRIVATE_KEY=your_wallet_private_key`
   - `CHAIN_ID=11155111`
4. Initialize DB schema:
   - `python -m backend.app.database`
5. Start server:
   - `uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000`
6. Open:
   - `http://127.0.0.1:8000`

## Smart Contract Deploy
1. `cd smart_contract`
2. `npm install`
3. Create `smart_contract/.env` from `.env.example` and fill values.
4. Deploy:
   - `npx hardhat run scripts/deploy.js --network sepolia`
5. Copy deployed address to root `.env` as `CONTRACT_ADDRESS`.

## Backfill Existing Records (Neon + Sepolia)
If you already had issues before blockchain integration, run this once:

- `python -m backend.app.backfill_hashes`

This will:
- Compute deterministic hash for every existing issue.
- Save hash to `issues.hash` in Neon.
- Push hash to Sepolia (only when on-chain hash is missing/different).
