import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

url = 'https://ip.decodo.com/json'
username = os.environ["PROXY_USER"]
password = os.environ["PROXY_PASS"]
proxy = f"http://{username}:{password}@kr.decodo.com:10000"
result = requests.get(url, proxies = {
    'http': proxy,
    'https': proxy
})
print(result.text)
