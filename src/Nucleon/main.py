import boto3
import PyPDF2
from io import BytesIO
import json
import datetime
import os

s3 = boto3.client('s3')
textract = boto3.client('textract')

Bucket = "nucleus-demo-jyoti"
# folder_path = "final-testing/final-testing/Banyan-Hospital/SUNIL-JOHARY"
FOLDER_PATH = os.getenv('FOLDER_PATH')
print("222",FOLDER_PATH)

pdf_text = ""
image_text = ""
supported_image_formats = ('.jpeg', '.jpg', '.png')

bedrock_runtime = boto3.client(
        service_name="bedrock-runtime",
        region_name="us-east-1",
    )


# List all objects in the bucket
response = s3.list_objects_v2(Bucket=Bucket , Prefix=FOLDER_PATH)

# Check if the bucket contains any objects
if 'Contents' in response:
    for obj in response['Contents']:
        print(obj['Key'])
else:
    print("Bucket is empty or does not exist.")


# Data JSON structure
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


if 'Contents' in response:
    for obj in response['Contents']:
        key = obj['Key']
        
        # Check if the object is a PDF
        if key.lower().endswith('.pdf'):
            # Download the PDF file from S3
            pdf_obj = s3.get_object(Bucket=Bucket, Key=key)
            pdf_data = pdf_obj['Body'].read()
            
            # Extract text from the PDF using PyPDF2
            pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_data))
            for page in pdf_reader.pages:
                pdf_text += page.extract_text() + "\n"
        
        # Check if the object is an image
        elif key.lower().endswith(supported_image_formats):
            # Call Textract to extract text from the image
            textract_response = textract.detect_document_text(
                Document={'S3Object': {'Bucket': Bucket, 'Name': key}}
            )
            
            # Extract text blocks from the response
            for block in textract_response['Blocks']:
                if block['BlockType'] == 'LINE':
                    image_text += block['Text'] + "\n"
else:
    print("Bucket is empty or does not exist.")

combined_text = pdf_text + image_text


# @logger.inject_lambda_context(log_event=True)
def lambda_handler(event, context):
    # event_body = json.loads(event["Records"][0]["body"])

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

    # Send the request to the Bedrock model
    print("Request sent to Bedrock model")
    print(datetime.datetime.now())
    response = bedrock_runtime.invoke_model(
        modelId="anthropic.claude-3-sonnet-20240229-v1:0",
        body=body
    )
    
    # Send the request to the Bedrock model
    print("Request sent to Bedrock model")
    print(datetime.datetime.now())
    response = bedrock_runtime.invoke_model(
        modelId="anthropic.claude-3-sonnet-20240229-v1:0",
        body=body
    )

    # Read and parse the response
    response_body = json.loads(response.get("body").read())

    # Extracted entities
    print("Response from Bedrock model:")
    print(response_body)
    result=response_body['content'][0]['text']

     # Parse the result string to JSON
    try:
        result_json = json.loads(result)
        print(json.dumps(result_json, indent=4))
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        result_json = {"error": "Failed to parse JSON response"}

    # print(result)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
        },
        "body": json.dumps(result_json),
    }
