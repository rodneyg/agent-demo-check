import json
from openai import OpenAI
client = OpenAI(api_key="sk-test-FAKEFAKEFAKEFAKEFAKE1234")
response = client.responses.create(model="demo", input="Hello")
result = json.loads(response.output_text)
