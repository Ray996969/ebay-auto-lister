# eBay Auto Lister (AI-Assisted)

An automated tool built with FastAPI and vanilla JavaScript that scans product packaging images using OpenAI's GPT-4o, extracts structured metadata, uploads images to AWS S3, and automatically compiles an eBay UK compliant CSV upload sheet.

## Features
- **AI Image Recognition:** Uses `gpt-4o` to dynamically predict official eBay Category IDs and fill out mandatory item specifics (Brand, Type, Model).
- **Cloud Storage:** Automatically streams uploaded product images to an AWS S3 bucket to generate public picture URLs.
- **Data Compilation:** Uses Pandas to seamlessly merge new product rows under strict eBay formatting headers without corrupting template directives.
- **Developer Sandbox:** Features a built-in frontend "One-Click Mock Mode" to verify workflow components without draining live API tokens.

## Tech Stack
- **Frontend:** HTML5, CSS3 (Flexbox), JavaScript (Fetch API, FormData)
- **Backend:** Python, FastAPI, Uvicorn, Pandas, Boto3 (AWS SDK), OpenAI API

## Setup Instructions
1. Clone the repository.
2. Create a local `.env` file based on `.env.example` and add your credentials.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt