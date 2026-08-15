## [opaphenia.com](https://www.opaphenia.com)
The project concept is explained in more detail [here](https://www.opaphenia.com/tombo09/04)


## Project Concept
```text
The idea of this project is to create a simple bridge between an easy-to-use interface and blockchain.

Users can register an account with a unique username.
After registration, they can write strings, for example thoughts, ideas, predictions, impulses, code or whatever.
Each string is combined with the username and the hash algorithm version used at that time. This combined string is then hashed.

The resulting hash is attached as input data to an Ethereum transaction from Address A to Address A.
Since no ETH is transferred to another party, the only direct cost is the gas fee.

All written strings are displayed inside the user’s account. By clicking on a string, the user can view its details, including:

* the block time,
* the hash of the string,
* the transaction ID,
* and a direct Etherscan link to the transaction on the blockchain.

```
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
