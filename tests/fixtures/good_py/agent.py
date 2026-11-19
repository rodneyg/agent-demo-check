import json
import logging
from openai import OpenAI, RateLimitError
from tenacity import retry, stop_after_attempt, wait_random_exponential
logger = logging.getLogger(__name__)
client = OpenAI(timeout=10, max_retries=2)

@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(max=8))
def run():
    try:
        response = client.responses.create(model="demo", input="Hello")
        logger.info("request=%s", response._request_id)
        return json.loads(response.output_text)
    except RateLimitError:
        logger.exception("Provider rate limit or quota exhausted")
        raise
    except json.JSONDecodeError:
        logger.exception("Invalid output")
        return {"error": "Please try again"}
