The project concept is explained in more detail [here](https://www.opaphenia.com/tombo09/04)

## How it works
```text
Create Thought
→ Store in PostgreSQL
→ Prepare and sign Ethereum transaction
→ Broadcast transaction
→ Successful receipt → Thought becomes public
→ Track confirmations
→ Finalize after configured confirmation depth
```

The application persists transaction state so interrupted broadcasts can be recovered without creating unnecessary new transactions.

## Installation
Clone the repository:
```bash
git clone https://github.com/tombo09/opaphenia.git
cd opaphenia
```

Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate
```

Install the dependencies:
```bash
pip install -r requirements.txt
```
Create a .env file and configure the required database, application, Ethereum and external-service environment variables.
```bash
cp .env.example .env
# Edit .env with your configuration
```
Run the database migrations, then start the application:
```bash
uvicorn app.main:app --reload
```

The application is then available locally at:
http://127.0.0.1:8000

Run the test suite with:
pytest
