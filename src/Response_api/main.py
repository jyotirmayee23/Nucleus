import json
import boto3
import uuid
import os

ssm_client = boto3.client('ssm')

def lambda_handler(event, context):

    body_content = event['body']
    
    # Parse the JSON string to get a Python dictionary
    body_dict = json.loads(body_content)
    
    # Extract the job_id from the parsed dictionary
    job_id = body_dict.get('job_id')
    
    
    print(f"Extracted job_id: {job_id}")
    parameter_name = job_id
    response = ssm_client.get_parameter(Name=parameter_name)
    # job_status = response['Parameter']['Value']
    job_status = json.loads(response['Parameter']['Value'])
    print(f"Job status: {job_status}")
    
    # Return the response immediately
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
        },
        "body": json.dumps({"status": job_status}),
    }
