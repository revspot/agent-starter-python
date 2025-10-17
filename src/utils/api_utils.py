import os
from dotenv import load_dotenv
import aiohttp
from functools import wraps
import logging

logger = logging.getLogger("livspace-agent")

load_dotenv(".env.local")

# --- POST Auth API ---
async def fetch_new_token():
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url = "https://ls-proxy.revspot.ai/canvas/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=aiohttp.BasicAuth(os.getenv("CLIENT_ID"), os.getenv("CLIENT_SECRET")),
            data={"grant_type": "client_credentials"},
        ) as resp:
            if resp.status != 200:
                raise Exception(f"Auth API failed: {resp.status}")
            data = await resp.json()
            return data["access_token"] 

# --- Decorator ---
def with_token_retry(get_api_func):
    @wraps(get_api_func)
    async def wrapper(*args, **kwargs):
        tried_refresh = False
        headers = kwargs.get("headers") or {}

        bearer_token = os.getenv("BEARER_TOKEN")
        if not bearer_token:
            bearer_token = await fetch_new_token()
            os.environ["BEARER_TOKEN"] = bearer_token
            
        headers = {**headers, "Authorization": f"Bearer {bearer_token}"}

        while True:
            try:
                return await get_api_func(*args, headers=headers, **kwargs)
            except aiohttp.ClientResponseError as e:
                if e.status in (401, 403) and not tried_refresh:
                    logger.warning("⚠️ Token expired, refreshing...")
                    bearer_token = await fetch_new_token()
                    os.environ["BEARER_TOKEN"] = bearer_token
                    headers = {**headers, "Authorization": f"Bearer {bearer_token}"}
                    tried_refresh = True
                else:
                    raise
    return wrapper

# --- GET API Data ---
@with_token_retry
async def get_api_data_async(
    url: str,
    params: dict = None,
    headers: dict = None,
    timeout: int = 10
):
    """
    Sends an asynchronous GET request to the given API endpoint.

    Args:
        url (str): The API endpoint URL.
        params (dict, optional): Query parameters for the request.
        headers (dict, optional): HTTP headers for the request.
        timeout (int, optional): Timeout in seconds (default: 10).

    Returns:
        dict or str: JSON response if available, else raw text.
    """

    logger.info(f"Getting API data from {url} with params {params}")

    timeout = aiohttp.ClientTimeout(total=timeout)
    headers = headers or {}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params, headers=headers) as response:
            if response.status != 200:
                # raise error so decorator can catch 401
                response.raise_for_status()

            try:
                logger.info(f"Response from {url} with params {params} is {await response.text()}")
                return await response.json()
            except aiohttp.ContentTypeError:
                return await response.text()
