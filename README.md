# Job Apply Agent

AI-assisted job application agent with a FastAPI backend, Streamlit frontend, SQLite database, and Playwright browser automation for LinkedIn Easy Apply.

## Tech Stack

- Backend: FastAPI
- Frontend: Streamlit
- Database: SQLite with SQLAlchemy async and `aiosqlite`
- Browser automation: Playwright
- AI provider: Groq

## Project Structure

```text
backend/      FastAPI API, database models, auth, agent endpoints
frontend/     Streamlit user interface
automation/   LinkedIn scraping and application automation
data/         Local SQLite database and runtime files
```

## Setup

1. Create or activate the virtual environment:

```powershell
.\env\Scripts\activate
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
playwright install chromium
```

3. Create your local `.env` file:

```powershell
copy .env.example .env
```

4. Fill these values in `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
LINKEDIN_EMAIL=your_linkedin_email
LINKEDIN_PASSWORD=your_linkedin_password
SECRET_KEY=change-this-to-a-random-secret-string
DATABASE_URL=sqlite+aiosqlite:///./data/autoapplier.db
```

Do not commit `.env`, browser profiles, database files, logs, screenshots, or cache files.

## Run Backend

```powershell
.\env\Scripts\python.exe -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend URL:

```text
http://localhost:8000
```

Health check:

```text
http://localhost:8000/health
```

## Run Frontend

Open a second terminal and run:

```powershell
.\env\Scripts\streamlit.exe run frontend/app.py --server.port 8501
```

Frontend URL:

```text
http://localhost:8501
```

## First-Time App Use

1. Start backend and frontend.
2. Open `http://localhost:8501`.
3. Register or log in.
4. Complete your profile.
5. Add skills, experience, education, preferred roles, locations, and resume text.
6. Go to the AI Job Agent page.
7. Choose job titles, locations, max applications, and LinkedIn as the site.
8. Launch the agent.

## Apply To One LinkedIn Job From Terminal

After your profile exists in the app database, run:

```powershell
.\env\Scripts\python.exe automation\linkedin_easy_apply.py --max-cards 25
```

Optional custom search:

```powershell
.\env\Scripts\python.exe automation\linkedin_easy_apply.py --search "python developer|India" --max-cards 25
```

The script:

- Uses the first user from `data/autoapplier.db` unless `--user-id` is provided.
- Opens/uses the LinkedIn browser profile from `LINKEDIN_USER_DATA_DIR`.
- Searches LinkedIn Easy Apply jobs.
- Attempts one application.
- Records the result in the `job_applications` table.

If LinkedIn asks for verification or CAPTCHA, complete it manually in the browser window, then let the automation continue.

## Git Hygiene

The `.gitignore` excludes local runtime and secret files such as:

- `.env`
- `env/`, `.venv/`
- `__pycache__/`
- `*.pyc`
- `*.log`, `*.err`
- `data/*.db`
- `data/linkedin_browser_profile/`
- `debug_screenshots/`

## Useful Commands

Check Git status:

```powershell
git status
```

Push code:

```powershell
git add README.md .gitignore backend frontend automation config.py requirements.txt test.py test_scraper.py data/.gitkeep .env.example
git commit -m "Add project README"
git push
```
