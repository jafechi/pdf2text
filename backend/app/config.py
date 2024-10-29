import os

import boto3

AWS_REGION = os.getenv('AWS_REGION')
BUCKET_NAME = os.getenv('AWS_BUCKET_NAME')
S3_RAW_FOLDER = os.getenv('S3_RAW_FOLDER')
S3_PROCESSED_FOLDER = os.getenv('S3_PROCESSED_FOLDER')

s3_client = boto3.client('s3',
                         region_name=os.getenv('AWS_REGION'),
                         aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
                         aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'))