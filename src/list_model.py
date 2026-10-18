import os
from dotenv import load_dotenv
from google import genai

load_dotenv()  # Load environment variables from .env file
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

for m in client.models.list():
    print(f"Model: {m.name}, Description: {m.description}")
    