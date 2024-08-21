import boto3
from io import BytesIO
import json
import datetime
import os
import fitz 
from PIL import Image
import pytesseract
import tempfile
from botocore.config import Config
import requests
import io
import uuid
from langchain.chains import LLMMathChain, LLMChain
from langchain.agents.agent_types import AgentType
from langchain.agents import Tool, initialize_agent
from langchain.prompts import PromptTemplate
from langchain_aws import ChatBedrock

base_temp_dir = '/tmp/images'
def ensure_directory_exists(directory_path):
    """Ensures the directory exists."""
    os.makedirs(directory_path, exist_ok=True)
supported_image_formats = ('.jpeg', '.jpg', '.png')

s3 = boto3.client('s3')
ssm_client = boto3.client('ssm')
textract = boto3.client('textract')

bedrock_runtime = boto3.client( 
        service_name="bedrock-runtime",
        region_name="us-east-1",
    )

# radiological_investigations_str = ", ".join(radiological_investigations)

# response_text = "For Radiology charges, please refer to the following list of radiology investigations: " + radiological_investigations_str + ". Extract and sum the costs associated with these investigations."

data_json = {
        "total bill amount": "",
        "billing date": "",
        "hospital bill number": "",
        "room type":"",
        "room charges": "",
        "visit charges": "",
        "surgeon charges": "",
        "OT charges": "",
        "Anesthesia charges": "",
        "Assitant surgeon charges": "",
        "Pathology charges": "",
        "Pharmacy charges": "",
        "Minor procedure charges": "",
        "Radiology charges": "",
        "other charges": ""
    }

data_json_str = json.dumps(data_json)


# @logger.inject_lambda_context(log_event=True)
def lambda_handler(event, context):
    job_id = event['job_id']
    links = event.get('links', [])
    print(f"Links received: {links}")
    local_directory = "local_directory_path"
    image_text = ""
    pdf_image_text = ""

    # Download each file from the links
    all_table_info = []
    all_final_maps = {}
    
    
    for link in links:
        url_parts = link.split('/')
        bucket_name1 = url_parts[2]
        if '.s3.amazonaws.com' in bucket_name1:
            bucket_name = bucket_name1.rstrip('.s3.amazonaws.com')
            print("5")
        else:
            bucket_name = bucket_name1

        object_key = '/'.join(url_parts[3:])
        print(object_key)
        local_file_path = os.path.join(local_directory, object_key)

        if object_key.lower().endswith(supported_image_formats):
            # local_path = '/tmp/' + object_key
            # print("lp",local_path)
            # print("ok",object_key)
            
            local_file_id = str(uuid.uuid4())
            local_directory = '/tmp/images'
            local_file_path = os.path.join(local_directory, object_key.rsplit('/', 1)[0], local_file_id)
            ensure_directory_exists(os.path.dirname(local_file_path))
            s3.download_file(bucket_name, object_key, local_file_path)
            image = Image.open(local_file_path)
            text = pytesseract.image_to_string(image)
            image_text += text + '\n'
            # print(combined_text)
            
            # s3.download_file(bucket_name, object_key, f"{local_directory}/{object_key}")
        elif object_key.lower().endswith('.pdf'):
            local_file_id = str(uuid.uuid4())
            local_directory = '/tmp/images'
            local_file_path = os.path.join(local_directory, object_key.rsplit('/', 1)[0], local_file_id)
            # local_pdf_path = '/tmp/' + object_key
            print("ok",object_key)
            print("lp",local_file_path)
            ensure_directory_exists(os.path.dirname(local_file_path))
            s3.download_file(bucket_name, object_key, local_file_path)
            base_name = os.path.splitext(object_key.split('/')[-1])[0]
            print("bn",base_name)

            pdf_document = fitz.open(local_file_path)
            for page_number in range(len(pdf_document)):
                page = pdf_document.load_page(page_number)
                pix = page.get_pixmap()
                output_image_path = f'/tmp/{base_name}_page_{page_number + 1}.png'
                pix.save(output_image_path)

                image = Image.open(output_image_path)
                text = pytesseract.image_to_string(image)
                pdf_image_text += text + '\n'
            print("pit",pdf_image_text)

    combined_text = image_text + pdf_image_text
                
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4000,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": combined_text},
                    {"type": "text", "text": "You are a document entity extraction specialist. Given above the document content, your task is to extract the text value of the following entities:"},
                    {"type": "text", "text": data_json_str},
                    {"type": "text", "text": "The JSON schema must be followed during the extraction.\nThe values must only include text found in the document."},
                    {"type": "text", "text": "Do not normalize any entity value."},
                    {"type": "text", "text": "Don’t include “Rs” while extracting values."},
                    {"type": "text", "text": "If an entity is not found in the document, set the entity value to null."},
                    # {"type": "text", "text": "For each entity, provide the extracted value and a detailed explanation of how you arrived at this extraction. Include specific references to the text from the document that led to your extraction decision. For 'visit charges,' ensure to correctly calculate based on the number of occurrences in the document and verify the number of visits. If there are discrepancies, note them clearly.use the total value for calculation"},
                    {"type": "text", "text": "For visiting charges , only take visitng charges keyword please ignore any other charge for the calculation other than visit charge keyword and if the visit charge is 0 then dont take in to count for the occurences and justify the calculation.Dont take charges other than visit charges for visiting charges"},
                    {"type": "text", "text": "For Visting charges just mention no . of occurence of visitng charges with their costing of each particularly and then calculate and also remember strictly take only visit keyword only for this"},
                    {"type": "text", "text": "For Billing date , we only need to take the billing date of hospital bill only"},
                    {"type": "text", "text": "For Room charges include room charges + nursing charges also"},
                    {"type": "text", "text": "For Room type only get the type keyword"},
                    {"type": "text", "text": "For 'Pathology charges,' only include the charges for the listed pathological investigations."},
                    {"type": "text", "text": "extracted text are like key and then value in next line , so answer for any key will be most probably in the next value"},
                    {"type": "text", "text": "For pharmacy charge incase check for all the total amount of pharmacy and then add it and then give total amount and ignore the discount part."},
                    # {"type": "text", "text": "See for other charges we have to take the total calculation of all the bills passed which should be mentioned in total amount or total bill. Subtract the sum of the charges mentioned in the data_json_str (e.g., room charges, surgeon charges, etc.) from the total bill amount, and the result will be the value for 'other charges.'"},
                    {"type": "text", "text": "Only return the values for each json (dont include explanation or calculation)"},
                    {"type": "text", "text": "Only return the values for each json and not explanation "},
                    # {"type": "text", "text": "can u give the explanation of each value conclusion"},
                    # {"type": "text", "text": response_text},
                    # {"type": "text", "text": "For Radiology charges, please refer to the following list of radiology investigations: " + radiological_investigations + ". Extract and sum the costs associated with these investigations."},
                    # {"type": "text", "text": "For each entity, provide the extracted value and an explanation of how you arrived at this extraction. Include specific references to the text from the document that led to your extraction decision."},
                    #  {"type": "text", "text": "For each entity, provide the extracted value and a detailed explanation of how you arrived at this extraction. Include specific references to the text from the document that led to your extraction decision. For 'visit charges,' provide the exact line or section from the document used to determine the charge amount and verify the number of visits if mentioned. If the explanation includes calculations, ensure that they are based on verifiable document content."}
                ],
            }
        ],
    })

    response = bedrock_runtime.invoke_model(
        modelId="anthropic.claude-3-sonnet-20240229-v1:0",
        body=body
    )

    # # Read and parse the response
    response_body = json.loads(response.get("body").read())

    # Extracted entities
    print("Response from Bedrock model:")
    print(response_body)
    result = response_body['content'][0]['text']

     # Parse the result string to JSON
    try:
        result_json = json.loads(result)
        # print(json.dumps(result_json, indent=4))
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        result_json = {"error": "Failed to parse JSON response"}



    # response_value = "Example Response from Secondary Lambda"

    combined_result = {
        "status": "Done",
        "response": result_json
    }

    combined_result_str = json.dumps(combined_result)

    ssm_client.put_parameter(
        Name=job_id,
        Value=combined_result_str,
        Type='String',
        Overwrite=True
    )
    

    # print(result)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
        },
        "body": json.dumps(combined_result_str),
    }
