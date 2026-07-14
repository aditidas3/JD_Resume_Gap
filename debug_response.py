from dotenv import load_dotenv
load_dotenv()

import os
from openai import OpenAI

client = OpenAI(base_url=os.environ["BASE_URL"], api_key=os.environ["OPENROUTER_API_KEY"])

response = client.chat.completions.create(
    model=os.environ["OPENROUTER_MODEL"],
    max_tokens=1500,
    messages=[{"role": "user", "content": "Return this exact JSON, nothing else: {\"test\": \"hello\"}"}],
)

print("finish_reason:", response.choices[0].finish_reason)
print("message.content:", repr(response.choices[0].message.content))
print("full message object:", response.choices[0].message)
if hasattr(response, "usage"):
    print("usage:", response.usage)
