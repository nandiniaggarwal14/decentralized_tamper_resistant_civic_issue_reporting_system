# Decentralized Tamper-Resistant Civic Issue Reporting System

Basic full-stack MVP with:
- Backend: FastAPI
- Frontend: HTML, CSS, JavaScript
- Storage: Neon PostgreSQL via `DATABASE_URL` in `.env`

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

## Run
1. Create and activate virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Create `.env` in project root and add:
   - `DATABASE_URL=your_neon_postgres_connection_string`
4. Initialize DB schema:
   - `python -m backend.app.database`
5. Start server:
   - `uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000`
6. Open:
   - `http://127.0.0.1:8000`
