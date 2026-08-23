import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
model = os.getenv("GROQ_MODEL")

print("API key loaded:", bool(api_key))
print("Model:", model)


client = Groq(
    api_key=api_key
)


response = client.chat.completions.create(

    model=model,

    messages=[
        {
            "role": "system",
            "content": (
                "You are a helpful AI assistant. "
                "Answer clearly and concisely."
            )
        },
        {
            "role": "user",
            "content": "What is cricket?"
        }
    ],

    temperature=0.2,

    max_tokens=300
)


print("\n========================================")
print("GROQ RESPONSE")
print("========================================")

print(
    response.choices[0].message.content
)