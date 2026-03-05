# NIMA – Request-to-animation model

NIMA is a Flask-based system that generates Manim CE animations from natural-language prompts. It includes a retrieval-augmented generation pipeline, code validation, database logging, and automated rendering.

## Features

- Converts user prompts into Manim CE v0.18.0 scenes.
- Supports algebra, geometry, calculus, and other mathematical domains.
- Multi-step pipeline: request analysis, planning, generation, refinement, and polishing.
- Python and Manim syntax validation.
- Ensures valid Scene classes; detects errors, warnings, and overlapping elements.
- RAG retrieval of golden examples and domain-specific guidance.
- Database logging (PostgreSQL) with optional enable/disable.
- Uses OpenAI API for reasoning and iterative code improvement.
- Automated rendering pipeline with outputs: video, code, logs, and metadata.

## Project Structure

project/
│
├── app.py                     # Flask server
├── algorithms/                # Core logic
│   ├── request_utils.py       # Prompt analysis and planning
│   ├── generation.py          # Code generation and refinement
│   ├── validation.py          # Syntax and quality checks
│   └── ...                    # Other algorithm helpers
│
├── database/
│   ├── database.py            # Database connection and helpers
│   └── schema.sql             # PostgreSQL schema
│
├── static/                    # Front-end assets (CSS, JS)
├── templates/                 # HTML templates for Flask
├── outputs/                   # Generated videos, logs, and code
└── README.md                  # Project documentation


## Requirements

flask  
openai  
python-dotenv  
psycopg2-binary  
manimce  

Install dependencies:
pip install -r requirements.txt

## Environment Variables

Create a `.env` file with:

OPENAI_API_KEY=your_api_key  
DB_CONNECTION_STRING=postgresql://user:password@host:port/dbname  
USE_DATABASE=true  

Set `USE_DATABASE=false` to disable database usage.

## Running the Application

Start the Flask development server:

python app.py

The app runs at:

http://127.0.0.1:5000

## Workflow Overview

1. User submits a prompt.  
2. NIMA analyzes the request and generates an animation plan.  
3. RAG retrieves relevant examples and guidance.  
4. Manim code is generated.  
5. Code is validated and improved.  
6. Rendering is executed via Manim.  
7. Outputs (video, code, logs) are returned.

## Extending the Dataset

- Add more examples to improve RAG retrieval.  
- Extend domains like physics, linear algebra, statistics.  
- Add structured explanations to guide generation.

## Notes

- Requires Manim CE installed locally.  
- Development server only; use a proper WSGI server for production.


**Example:**

![Narrated demonstration](./example.mp4)

[Watch the narrated demonstration video](./example.mp4)
