from dotenv import load_dotenv
import os

# Load .flaskenv before importing app
load_dotenv('.flaskenv')

from main import app

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5001)
