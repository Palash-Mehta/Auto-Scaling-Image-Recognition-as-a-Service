from variables import KEY_FILE, ACCESS_KEY, SECRET_KEY, REGION, INPUT_BUCKET, OUTPUT_BUCKET, USERNAME
import sys
import boto3
import subprocess
from botocore.exceptions import ClientError
import logging
import uuid

# Initialize S3
s3 = boto3.resource(
    's3',
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    region_name=REGION
)
s3_client = boto3.client(
    's3',
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    region_name=REGION
)

# Initialize SQS
sqs = boto3.client(
        'sqs',
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name=REGION
    )
sqs_client = boto3.resource(
        'sqs',
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name=REGION
    )
request_queue = sqs.get_queue_by_name(QueueName='request_queue.fifo')
response_queue = sqs.get_queue_by_name(QueueName='response_queue.fifo')

# Get the image name to be processed
image_name = sys.argv[1]

# Download the image from S3 input bucket and store in images folder
s3_client.download_file(INPUT_BUCKET, image_name, 'images/' + image_name)


def upload_file_to_S3(file_name, bucket, object_name=None):

    """Upload a file to an S3 bucket
    :param file_name: File to upload
    :param bucket: Bucket to upload to
    :param object_name: S3 object name. If not specified then file_name is used
    :return: True if file was uploaded, else False
    """
    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = file_name

    # Upload the file
    try:
        response = s3_client.upload_file(file_name, bucket, object_name)
    except ClientError as error:
        logging.error(error)
        return False
    return True


try:
    # Run the classification program by passing the image as the argument
    prediction = subprocess.check_output("python3 image_classification.py " + "images/" + image_name, shell=True)
    prediction = prediction.decode('utf-8')
    # Write the prediction to a text file
    with open("prediction.txt", "w") as text_file:
        text_file.write("(" + image_name.split(".")[0] + ", " + str(prediction) + ")")
    # Save the file to S3 bucket
    upload_file_to_S3("prediction.txt", OUTPUT_BUCKET, image_name.split(".")[0])
    # Send the message to response SQS
    response_queue.send_message(
        MessageBody="(" + image_name.split(".")[0] + ", " + str(prediction) + ")",
        MessageGroupId="prediction",
        MessageDeduplicationId=str(uuid.uuid1()))
except Exception as e:
    # Some error occurred and write the error message to a text file
    with open("prediction.txt", "w") as text_file:
        text_file.write(str(e))
    # Save the file to S3 bucket
    upload_file_to_S3("prediction.txt", OUTPUT_BUCKET, image_name.split(".")[0])

