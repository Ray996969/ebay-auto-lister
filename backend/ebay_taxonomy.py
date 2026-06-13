import base64
import requests
import os
from dotenv import load_dotenv

load_dotenv()

    # get the application token, by using the two  password, this is becasue ebay use oauth 2.0 which without
    #sharing the real password
def get_ebay_application_token():
    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")
    
    # 1. Base64 encode the Client ID and Client Secret together
    credentials = f"{client_id}:{client_secret}"
    encoded_creds = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    
    # 2. eBay Sandbox OAuth Endpoint
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {encoded_creds}"
    }
    
    # 3. Requesting scoping for public metadata (Taxonomy API access)
    payload = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    
    print("Requesting eBay sandbox access token...")

    # request is a python function allow to send http request to the webiste/API , just like fetch in js.
    response = requests.post(url, headers=headers, data=payload, timeout=20)

    print("Status code:", response.status_code)
    # print(response.json()["access_token"]) # this will show the token(application access token), and the expires time which is about 7200 seconds 

    return response.json()["access_token"]


def get_uk_category_tree_id(access_token):

    # 1. Define the Endpoint (Remember to use 'sandbox' for testing!)
    url = "https://api.ebay.com/commerce/taxonomy/v1/get_default_category_tree_id"

    # 2. Package your authorization rule
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    # 3. Package your market filter rule
    params = {
        "marketplace_id": "EBAY_GB"
    }

    # 4. Fire the request tool using all three ingredients
    response = requests.get(url, headers=headers, params=params)

    return response.json()["categoryTreeId"]





if __name__ == "__main__":
    access_Token =  get_ebay_application_token()
    uk_tree_data = get_uk_category_tree_id(access_Token)
    print("UK Tree Data Response:", uk_tree_data)



