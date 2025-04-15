# Copyright 2022 Tecnativa - David Vidal
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging

from lxml import etree
import requests
import hashlib
import time
import json

_logger = logging.getLogger(__name__)

BL_API_URL = {
    "test": "http://admin.banlingkit.com:8012",
    "prod": "http://admin.banlingkit.com:8012",
}


class BanlingkitExpressRequest:
    """Interface between Banlingkit Express SOAP API and Odoo recordset.
    Abstract Banlingkit Express API Operations to connect them with Odoo
    """
    cid = False
    salt = False
    

    def __init__(self, api_cid, api_salt, prod=False):
        self.cid = api_cid
        self.salt = api_salt
        # We'll store raw xml request/responses in this properties
        self.bl_last_request = False
        self.bl_last_response = False
        self.url = BL_API_URL["prod"] if prod else BL_API_URL["test"]
        self.headers = {
            "Content-Type": "application/json;charset=UTF-8"
        }
   

    @staticmethod
    def _format_error(error):
        """Common method to format error outputs

        :param zeep.objects.ArrayOfErrorResult error: Error response or None
        :return list: List of tuples with errors (code, description)
        """
        if not error:
            return []
        return [(x.ErrorCode, x.ErrorMessage) for x in error.ErrorResult]

    @staticmethod
    def _format_document(documents):
        """Common method to format document outputs

        :param list document: List of documents
        """
        if not documents:
            return []
        return [(x.FileName, x.FileContent) for x in documents.Document]

    def manifest_shipping(self, shipping_values):
        """Create shipping with the proper picking values

        :param dict shipping_values: Shippng values prepared from Odoo
        :return tuple: tuple containing:
            list: Error Codes
            list: Document binaries
            str: Shipping code
        """

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json",
        }
        # Generate the secret key for the API
        url = self.url + "/invoice/create"
        
        headers = {
            "salt": self.salt,
        }

        data = [shipping_values]

        # Send the request to the API
        print("Request URL: ", url)
        print("Request Headers: ", headers)
        print("Request Data: ", data)
        print("Request Headers: ", headers)

        response = requests.post(url, headers=headers, json=data)
        print("Response Status Code: ", response.status_code)
        print("Response Headers: ", response.headers)
        print("Response Data: ", response.text)

        # logging
        _logger.info("Request URL: %s", url)
        _logger.info("Request Headers: %s", headers)
        _logger.info("Request Data: %s", data)
        _logger.info("Response Status Code: %s", response.status_code)
        _logger.info("Response Headers: %s", response.headers)
        _logger.info("Response Data: %s", response.text)

        cNo = ""
        printUrl = ""

        # check the response status code and response data
        if response.status_code != 200:
            raise Exception("Error in request")
        
        if( response.json().get("code") != 1):
            raise Exception("Error in response")
        if response.json().get("code") == 1:
            cNo = self.api_cid + shipping_values.get("sourceCode")
        

        return (
            "1",
            printUrl,
            cNo,
        )

    def get_tracking(self, shipping_code):
        """Gather tracking status of shipping code. Maps to API's GetTracking.

        :param str shipping_code: Shipping code
        :return tuple: contents of tuple:
            list: error codes in the form of tuples (code, descriptions)
            list: of OrderedDict with statuses
        """
        values = dict(self._credentials(), ShippingCode=shipping_code)
        response = self.client.service.GetTracking(**values)
        return (
            self._format_error(response.ErrorCodes),
            (response.Tracking and serialize_object(response.Tracking.Tracking) or []),
        )

    def get_documents(self, shipping_code):
        """Get shipping documents (label)

        :param str shipping_code: Shipping code
        :return tuple: tuple containing:
            list: error codes in the form of tuples (code, descriptions)
            list: documents in the form of tuples (file_content, file_name)
        """
        values = dict(self._credentials(), ShippingCode=shipping_code)
        response = self.client.service.GetDocuments(**values)
        return (
            self._format_error(response.ErrorCodes),
            self._format_document(response.Documents),
        )

    def get_documents_multi(
        self,
        shipping_codes,
        document_code="LASER_MAIN_ES",
        model_code="SINGLE",
        kind_code="PDF",
        offset=0,
    ):
        """Get shipping codes documents

        :param str shipping_codes: shipping codes separated by ;
        :param str document_code: Document code, defaults to LASER_MAIN_ES
        :param str model_code: (SINGLE|MULTI1|MULTI3|MULTI4), defaults to SINGLE
            - SINGLE: Thermical single label printer
            - MULTI1: Sheet format 1 label per sheet
            - MULTI3: Portrait 3 labels per sheet
            - MULTI4: Landscape 4 labels per sheet
        :param str kind_code: (PDF|PNG|BMP), defaults to PDF
        :param int offset: Document offset, defaults to 0
        :return tuple: tuple containing:
            list: error codes in the form of tuples (code, descriptions)
            list: documents in the form of tuples (file_content, file_name)
        """
        url = "https://label.Banlingkit.com/BanlingkitPrint"
        timestamp = str(int(time.time()*1000))
        secret = self.get_secret(timestamp)
        data = {
            "icID": self.api_cid,
            "signature": secret,
            "cNos": shipping_codes,
            "ptemp": "label10x15_1",
        }
        response = requests.get(url, params=data)
        print("Response full url: ", response.request.url)
        print("Request URL: ", url)
        print("Request Headers: ", self.headers)
        print("Request Data: ", data)
        print("Response Status Code: ", response.status_code)
        print("Response: ", response.text)
        if response.status_code != 200:
            raise Exception("Error in request")
        if response.json().get("ErrorCode") != 0:
            raise Exception("Error in response")
        return response.json()

    def get_service_types(self):
        """Gets the hired service types. Maps to API's GetServiceTypes.

        :return tuple: contents of tuple:
            list: error codes in the form of tuples (code, descriptions)
            list: list of tuples (service_code, service_description):
        """
        response = self.client.service.GetServiceTypes(**self._credentials())
        return (
            self._format_error(response.ErrorCodes),
            [
                (x.ShippingTypeCode, x.ShippingTypeDescription)
                for x in response.Services.ClientShippingType
            ],
        )

    def cancel_shipping(self, shipping_code):
        """Cancel a shipping by code

        :param str shipping_code: Shipping code
        :return str: Error codes
        """
        values = dict(self._credentials(), ShippingCode=shipping_code)
        response = self.client.service.CancelShipping(**values)
        return [(x.ErrorCode, x.ErrorMessage) for x in response]

    def report_shipping(
        self, process_code="ODOO", document_type="XLSX", from_date=None, to_date=None
    ):
        """Get the shippings manifest. Mapped to API's ReportShipping

        :param str process_code: (ODOO|MAGENTO|PRESTASHOP), defaults to "ODOO"
        :param str document_type: Report type, defaults to "XLSX" (PDF|XLSX)
        :param str from_date: Date from "yyyy-mm-dd", defaults to None.
        :param str to_date: Date to "yyyy-mm-dd", defaults to None.
        :return tuple: tuple containing:
            list: error codes in the form of tuples (code, descriptions)
            list: documents in the form of tuples (file_content, file_name)
        """
        values = dict(
            self._credentials(),
            ProcessCode=process_code,
            DocumentKindCode=document_type,
            FromDate=from_date,
            ToDate=to_date,
        )
        response = self.client.service.ReportShipping(**values)
        return (
            self._format_error(response.ErrorCodes),
            self._format_document(response.Documents),
        )



    def create_request(self, delivery_date, min_hour, max_hour):
        """Create a shipping pickup request. CreateRequest API's mapping.

        :param datetime.date delivery_date: Delivery date
        :param str min_hour: Minimum pickup hour in format "HH:MM"
        :param str max_hour: Maximum pickup hour in format "HH:MM"
        :return tuple: tuple containing:
            list: Error codes
            str: Request shipping code
        """
        url = self.url + "/invoice/lists"
        timestamp = str(int(time.time()*1000))
        secret = self.get_secret(timestamp)
        headers = {
            "salt": self.salt,
        }
        # form-data data
        data = {
        }

        # Send the request to the API
        print("Request URL: ", url)
        
        response = requests.put(url, headers=headers, data=data)
        print("Response Status Code: ", response.status_code)
        print(response.text)
        return (response.status_code, response.text)
