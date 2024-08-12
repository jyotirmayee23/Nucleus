import boto3
from io import BytesIO
import json
import datetime
import os
# import PyPDF2
from pdf2image import convert_from_path
from PIL import Image
import tempfile
from botocore.config import Config
import requests
from PIL import Image
import io
from langchain.chains import LLMMathChain, LLMChain
from langchain.agents.agent_types import AgentType
from langchain.agents import Tool, initialize_agent
from langchain.prompts import PromptTemplate
from langchain_aws import ChatBedrock

images_dir = '/tmp/images'
supported_image_formats = ('.jpeg', '.jpg', '.png')

s3 = boto3.client('s3')
ssm_client = boto3.client('ssm')
textract = boto3.client('textract')

bedrock_runtime = boto3.client( 
        service_name="bedrock-runtime",
        region_name="us-east-1",
    )

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
    image_text = ""
    pdf_image_text = ""

    # Download each file from the links
    for link in links:
        url_parts = link.split('/')
        # print("url", url_parts)
        bucket_name1 = url_parts[2]
        if '.s3.amazonaws.com' in bucket_name1:
            bucket_name = bucket_name1.rstrip('.s3.amazonaws.com')
        else:
            bucket_name = bucket_name1

        print("er",bucket_name)

        object_key = '/'.join(url_parts[3:])
        
        print("key",object_key)

        if object_key.lower().endswith(supported_image_formats):
            # Call Textract to extract text from the image
            textract_response = textract.detect_document_text(
                Document={'S3Object': {'Bucket': bucket_name, 'Name': object_key}}
            )

            # Extract text blocks from the response
            for block in textract_response['Blocks']:
                if block['BlockType'] == 'LINE':
                    image_text += block['Text'] + "\n"
            # print("image_text_123", image_text)
        elif object_key.lower().endswith('.pdf'):
            local_path = '/tmp/' + object_key.split('/')[-1]
            print("Local path:", local_path)
            s3.download_file(bucket_name, object_key, local_path)

            images = convert_from_path(local_path)
            base_name = os.path.splitext(object_key.split('/')[-1])[0]
            print("base_name",base_name)

            # Process each image without uploading to S3
            for i, image in enumerate(images):
                image_file_name = f'{base_name}_{i+1}.png'
                # Save the image to a BytesIO object
                with io.BytesIO() as buffer:
                    image.save(buffer, format='PNG')
                    buffer.seek(0)
                    
                    # Send image to Textract
                    textract_response = textract.detect_document_text(
                        Document={'Bytes': buffer.getvalue()}
                    )
                    
                    # Extract text blocks from the response
                    for block in textract_response['Blocks']:
                        if block['BlockType'] == 'LINE':
                            pdf_image_text += block['Text'] + "\n"
                    # print(f"Extracted text from {image_file_name}:", pdf_image_text)
            # print(f"Extracted text from {image_file_name}:", pdf_image_text)

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
                    {"type": "text", "text": "Only return the values for each json (dont include explanation or calculation)"},
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
