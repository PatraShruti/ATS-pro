# ATS Pro 

ATS Pro  is a powerful, AI-driven Applicant Tracking System that analyzes, scores, and compares resumes against job descriptions. It uses Anthropic's Claude AI to provide actionable feedback for candidates and deep comparative analytics for hiring managers.

## Features

The application operates on a **Two-Flow System**:

### 1. Guest Flow (For Candidates)
* **Instant Resume Check:** Upload a resume (PDF, DOCX, or TXT) without creating an account.
* **Role-Specific Optimization:** Analyze the resume generally or against a specific job role.
* **AI Feedback:** Get a detailed ATS score, missing keywords, formatting tips, language rewrite suggestions, and an estimated ATS pass rate.

### 2. Company Flow (For Hiring Managers)
* **Secure Dashboard:** Registered companies get a full hiring dashboard with JWT-based authentication.
* **Job Role Management:** Create and manage open job roles with required skills and descriptions.
* **Deep Candidate Analysis:** Score candidates dynamically based on experience, skills, and keyword match for a specific job description.
* **Candidate Comparison:** Select multiple candidates and let the AI generate a ranked comparison, highlighting who fits best, skills gaps, and recommended interview questions.
* **Analytics:** Visual breakdowns of candidate quality, skill gaps, and hiring trends.

## Tech Stack

* **Backend:** Python, Flask, Gunicorn
* **Database:** SQLite (with WAL mode for better concurrency)
* **AI Integration:** Anthropic API (Claude 3.5 Sonnet)
* **Authentication:** PyJWT (JSON Web Tokens)
* **File Processing:** `pypdf`, `python-docx`

## Local Setup & Installation

### Prerequisites
Make sure you have **Python 3.8+** installed on your machine. You will also need an API key from [Anthropic](https://console.anthropic.com/).

