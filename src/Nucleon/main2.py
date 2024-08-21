import boto3
from io import BytesIO
import json
import datetime
import os
import fitz 
from PIL import Image
import tempfile
from botocore.config import Config
import requests
import io
from langchain.chains import LLMMathChain, LLMChain
from langchain.agents.agent_types import AgentType
from langchain.agents import Tool, initialize_agent
from langchain.prompts import PromptTemplate
from langchain_aws import ChatBedrock
from parser import (
    extract_text,
    map_word_id,
    extract_table_info,
    get_key_map,
    get_value_map,
    get_kv_map,
)

images_dir = '/tmp/images'
supported_image_formats = ('.jpeg', '.jpg', '.png')

s3 = boto3.client('s3')
ssm_client = boto3.client('ssm')
textract = boto3.client('textract')

bedrock_runtime = boto3.client( 
        service_name="bedrock-runtime",
        region_name="us-east-1",
    )

# radiological_investigations = [
#     "Chest X-ray",
#     "Abdominal X-ray",
#     "Pelvic X-ray",
#     "Skull X-ray",
#     "Spine X-ray",
#     "Limb X-ray",
#     "Mammography",
#     "CT Head",
#     "CT Chest",
#     "CT Abdomen",
#     "CT Pelvis",
#     "CT Spine",
#     "CT Angiography",
#     "CT Coronary Angiography",
#     "CT Pulmonary Angiography",
#     "CT Colonography",
#     "CT Enterography",
#     "CT Urography",
#     "CT Myelography",
#     "CT Perfusion",
#     "MRI Brain",
#     "MRI Spine",
#     "MRI Abdomen",
#     "MRI Pelvis",
#     "MRI Breast",
#     "MRI Angiography",
#     "MRI Cardiac",
#     "MRI Spectroscopy",
#     "MRI Enterography",
#     "MRI Urography",
#     "MRI Cholangiopancreatography (MRCP)",
#     "MRI Prostate",
#     "MRI Bone Marrow",
#     "MRI Whole Body",
#     "Ultrasound Abdomen",
#     "Ultrasound Pelvis",
#     "Ultrasound Obstetric",
#     "Ultrasound Breast",
#     "Ultrasound Thyroid",
#     "Ultrasound Doppler",
#     "Ultrasound Cardiac (Echocardiography)",
#     "Ultrasound Musculoskeletal",
#     "Ultrasound Carotid",
#     "Ultrasound Renal",
#     "Ultrasound Scrotum",
#     "Ultrasound Liver",
#     "Ultrasound Pancreas",
#     "Ultrasound Aorta",
#     "Ultrasound Appendix",
#     "Ultrasound Bladder",
#     "Ultrasound Gallbladder",
#     "Ultrasound Spleen",
#     "Ultrasound Transvaginal",
#     "Ultrasound Transrectal",
#     "Ultrasound Biopsy Guidance",
#     "Ultrasound Vascular Access",
#     "Nuclear Bone Scan",
#     "Nuclear Cardiac Stress Test",
#     "Nuclear Thyroid Scan",
#     "Nuclear Lung Scan (V/Q Scan)",
#     "Nuclear Renal Scan",
#     "Nuclear Liver Scan",
#     "Nuclear Gallbladder Scan (HIDA Scan)",
#     "PET-CT Scan",
#     "PET-MRI Scan",
#     "SPECT Scan",
#     "MUGA Scan",
#     "DEXA Bone Densitometry",
#     "Fluoroscopy",
#     "Barium Swallow",
#     "Barium Meal",
#     "Barium Enema",
#     "Hysterosalpingography (HSG)",
#     "Intravenous Pyelogram (IVP)",
#     "Retrograde Urethrogram (RUG)",
#     "Retrograde Pyelogram",
#     "Voiding Cystourethrogram (VCUG)",
#     "Sinogram",
#     "Fistulogram",
#     "Arthrogram",
#     "Myelogram",
#     "Sialogram",
#     "Cholangiogram",
#     "Angiogram",
#     "Venogram",
#     "Lymphangiogram",
#     "Bronchogram",
#     "Digital Subtraction Angiography (DSA)",
#     "Carotid Angiography",
#     "Coronary Angiography",
#     "Peripheral Angiography",
#     "Endoscopic Retrograde Cholangiopancreatography (ERCP)",
#     "Thoracoscopy",
#     "Bronchoscopy",
#     "Cystoscopy",
#     "Laparoscopy",
#     "Arthroscopy",
#     "Sinus X-ray",
#     "Sinus CT",
#     "Sinus MRI"
#   ]

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
    # image_text = ""
    # pdf_image_text = ""
    all_table_info = []
    all_final_maps = {}

    # Download each file from the links
    for link in links:
        url_parts = link.split('/')
        # print("url", url_parts)
        bucket_name1 = url_parts[2]
        if '.s3.amazonaws.com' in bucket_name1:
            bucket_name = bucket_name1.rstrip('.s3.amazonaws.com')
        else:
            bucket_name = bucket_name1

        # all_table_info = []
        # # all_final_maps = {}
        # all_final_maps = []


        print("er",bucket_name)

        object_key = '/'.join(url_parts[3:])
        
        print("key",object_key)

        if object_key.lower().endswith(supported_image_formats):
            # Call Textract to extract text from the image
            a_response = textract.analyze_document(
                Document={'S3Object': {'Bucket': bucket_name, 'Name': object_key}},
                FeatureTypes=["FORMS", "TABLES"],
            )


            word_map = map_word_id(a_response)
            table = extract_table_info(a_response, word_map)
            key_map = get_key_map(a_response, word_map)
            value_map = get_value_map(a_response, word_map)
            final_map = get_kv_map(key_map, value_map)
            # print("45",table)

            all_table_info.append(table)
            # print("3",all_table_info)
            # print("jj",json.dumps(all_table_info,indent=2))
            # all_final_maps.update(final_map)
            all_final_maps.update(final_map)
            print("maps",all_final_maps)

            
            # print("image_text_123", image_text)
        elif object_key.lower().endswith('.pdf'):
            local_path = '/tmp/' + object_key.split('/')[-1]
            print("Local path:", local_path)
            s3.download_file(bucket_name, object_key, local_path)
            base_name = os.path.splitext(object_key.split('/')[-1])[0]

            pdf_document = fitz.open(local_path)
            for page_number in range(len(pdf_document)):
                page = pdf_document.load_page(page_number)
                print("@",page)
                pix = page.get_pixmap()
                output_image_path = f'/tmp/{base_name}_page_{page_number + 1}.png'
                print("1",output_image_path)
                pix.save(output_image_path)


                with open(output_image_path, 'rb') as img_file:
                    img_bytes = img_file.read()
                    a_response = textract.analyze_document(
                        Document={'Bytes': img_bytes},
                        FeatureTypes=["FORMS", "TABLES"],
                    )

                    word_map = map_word_id(a_response)
                    table = extract_table_info(a_response, word_map)
                    print("@$%",json.dumps(table,indent=2))
                    key_map = get_key_map(a_response, word_map)
                    value_map = get_value_map(a_response, word_map)
                    final_map = get_kv_map(key_map, value_map)
                    all_table_info.append(table)
                    all_final_maps.update(final_map)
    # print("jj",json.dumps(all_table_info,indent=2))
    # print("jj",json.dumps(all_final_maps,indent=2))

    # combined_text = image_text + pdf_image_text
    # all_table_info.append(table)
    # all_final_maps.append(final_map)
    # all_final_maps.update(final_map)
    print("22s",all_table_info)
    print("23s",all_final_maps)
    

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4000,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": json.dumps(all_table_info)},
                    {"type": "text", "text": json.dumps(all_final_maps)},
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
                    {"type": "text", "text": "can u give the explanation of each value conclusion"},
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
