# Fake News Detection Web App

A beginner-friendly web-based fake news detection project built with Flask, SQLite, HTML, CSS, JavaScript, and the Google Gemini API.

This project is designed for:
- College mini projects
- Final year project demos
- Beginners learning Flask
- Students who want clean and simple code

## Features

- Analyze a news headline or short article
- Classify content as `Likely Real`, `Likely Fake`, or `Uncertain`
- Show confidence score, short explanation, and warning signs
- User signup and login system
- Password hashing using `werkzeug.security`
- Logged-in user history page
- Export history as CSV
- Clear history option
- Responsive modern UI
- Dark mode toggle

## Tech Stack

- Python 3
- Flask
- SQLite
- HTML5
- CSS3
- JavaScript
- Jinja2
- Google Gemini API

## Project Structure

```text
fake_news_project/
|-- app.py
|-- requirements.txt
|-- .env
|-- .env.example
|-- database.db
|-- README.md
|-- static/
|   |-- style.css
|   `-- script.js
`-- templates/
    |-- base.html
    |-- index.html
    |-- result.html
    |-- history.html
    |-- login.html
    |-- signup.html
    `-- about.html
```

## How It Works

1. The user enters a news headline or short article on the home page.
2. Flask validates the text input.
3. The app sends the text to the Gemini API with a prompt asking for JSON output.
4. Gemini returns:
   - Result
   - Confidence
   - Reason
   - Warning signs
5. Flask safely parses the JSON response.
6. The result is shown on the result page.
7. If the user is logged in, the analysis is stored in the SQLite history table.

## Database Tables

### `users`

- `id`
- `username`
- `email`
- `password_hash`

### `history`

- `id`
- `user_id`
- `news_text`
- `result`
- `confidence`
- `reason`
- `created_at`

## Gemini Prompt Used

```json
{
  "result": "REAL or FAKE or UNCERTAIN",
  "confidence": number,
  "reason": "short explanation",
  "warnings": ["warning1", "warning2"]
}
```

The app instructs Gemini to return only valid JSON so the backend can parse it safely.

## Installation

### 1. Clone or open the project folder

Place all project files inside your working directory.

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv
```

Activate it:

Windows:

```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create `.env`

Copy `.env.example` to `.env` and add your Gemini API key.

Example:

```env
SECRET_KEY=your-secret-key
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-1.5-flash
```

## How to Run

```bash
python app.py
```

Then open:

[http://127.0.0.1:5000](http://127.0.0.1:5000)

## Main Routes

- `/` -> Home page
- `/analyze` -> Analyze news text
- `/result` -> Show analysis result
- `/signup` -> Create account
- `/login` -> Login
- `/logout` -> Logout
- `/history` -> View saved history
- `/history/export` -> Download history CSV
- `/history/clear` -> Delete saved history
- `/about` -> About page

## Security Used

- Password hashing with Werkzeug
- Session-based login system
- Gemini API key stored in `.env`
- Basic input validation
- Safe JSON parsing

## Error Handling

The app handles:

- Missing Gemini API key
- Invalid Gemini JSON response
- Short or empty user input
- Network/API failures
- Invalid login
- Duplicate signup data
- History save failure

## Files Explanation

### `app.py`

Contains:
- Flask app setup
- Database connection helper
- Automatic table creation
- Login system
- Gemini analysis logic
- History management

### `templates/`

Contains all HTML pages using Jinja2.

### `static/style.css`

Contains:
- Gradient background
- Modern cards
- Buttons
- Forms
- Result badge colors
- Responsive layout

### `static/script.js`

Contains:
- Character count
- Loading spinner behavior
- Dark mode toggle
- Copy result button

## Beginner Notes

- This project is intentionally simple and easy to read.
- SQLite is used so no extra database setup is required.
- You can later improve it by adding ML datasets, charts, admin panel, or advanced fact-checking APIs.

## Suggested Demo Flow

1. Open the home page
2. Sign up and log in
3. Paste a news headline
4. Click Analyze
5. Show result badge, confidence, and explanation
6. Open history page
7. Export CSV for extra project demo value

## Important Limitation

This app uses Gemini for reasoning-based analysis. It gives a helpful AI opinion, but it does not guarantee that a news article is truly real or fake. For production-level fact checking, you would need trusted sources, verification pipelines, and datasets.

## Submission Tip

For college submission, you can describe this project as:

> A Flask-based web application that detects potentially fake news using the Google Gemini API and stores user analysis history in SQLite.
