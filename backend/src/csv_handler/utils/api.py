from typing import List
import requests
from .logger import console
import json
from central_config import OTC_CLIENT_API_URL



def verify_otc_api(licence_numbers: List):
        """
        This function sends a list of licence numbers to the endpoint at localhost:8000/otc/licences.

        Args:
            licence_numbers (List): A list of licence numbers.

        Returns:
            None
        """
        try:
            licence_numbers_list = set()
            console.log("Sending list to OTC API")
            console.log(licence_numbers)
            for key,registration in  licence_numbers.items():
                licence_numbers_list.add(registration.licence_number)
            console.log(licence_numbers_list)
            console.log(json.dumps(list(licence_numbers_list)))

            # console.log(licence_numbers)
            if OTC_CLIENT_API_URL != "OTC_API_URL is not set":
                url = OTC_CLIENT_API_URL
            else:
                 raise Exception("OTC_API_URL is not set")
            # url = "http://docker.for.mac.localhost:8000/api/v1/otc/licences"
            response = requests.post(url,data=json.dumps(list(licence_numbers_list)), headers={"Content-Type": "application/json"})
            # add a list as body of the request
            if response.status_code == 200:

                print("List sent successfully!")
                output = response.json()
                return output
            else:
                print("Failed to send list. Error:", response.status_code)
                print(response)
        except Exception as e:
            print(e)
