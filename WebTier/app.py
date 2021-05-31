from flask import Flask, flash, render_template, request, redirect, url_for, abort, current_app
from variables import ACCESS_KEY, SECRET_KEY, REGION, OUTPUT_BUCKET
from werkzeug.utils import secure_filename
import boto3
from botocore.exceptions import ClientError
import logging
import os
import uuid
import time
import threading

app = Flask(__name__)
app.config['UPLOAD_EXTENSIONS'] = ['.png', '.PNG', '.jpg', '.JPEG', '.JPG', ',jpeg']

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
sqs = boto3.resource(
        'sqs',
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name=REGION
    )
sqs_client = boto3.client(
        'sqs',
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name=REGION
    )
request_queue = sqs.get_queue_by_name(QueueName='request_queue.fifo')
response_queue = sqs.get_queue_by_name(QueueName='response_queue.fifo')


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
    except ClientError as e:
        logging.error(e)
        return False
    return True


# Get the length of response SQS queue
def get_queue_length():
    response_queue_dict = sqs_client.get_queue_attributes(
        QueueUrl=response_queue.url,
        AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
    )
    response_queue_length = int(response_queue_dict['Attributes']['ApproximateNumberOfMessages']) + int(response_queue_dict['Attributes']['ApproximateNumberOfMessagesNotVisible'])

    return response_queue_length


# Render landing page
@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')


# Select images, send SQS message, upload to S3
@app.route('/', methods=['POST'])
def upload_files():
    input_bucket_name = 'project1inputbucket'
    start = time.time()
    for uploaded_file in request.files.getlist('files'):
        """
            These attributes are also available
            file.filename               
            file.content_type
            file.content_length
            file.mimetype
        """
        if uploaded_file.filename == '':
            return "Please select a file"
        else:
            filename = secure_filename(uploaded_file.filename)
            file_ext = os.path.splitext(filename)[1]
            if file_ext not in current_app.config['UPLOAD_EXTENSIONS']:
                return "Invalid image", 400
            request_queue.send_message(
                MessageBody=filename,
                MessageGroupId='input_image',
                MessageDeduplicationId=str(uuid.uuid1()))
            uploaded_file.save(os.path.join('/tmp/', filename))
            upload_file_to_S3('/tmp/' + filename, input_bucket_name, filename)
    end = time.time()
    flash('Files uploaded successfully! Time taken ' + str(end - start))
    return redirect(url_for('home'))


# Get the prediction results from response SQS queue
@app.route('/results', methods=['GET', 'POST'])
def display_all_images():
    ans = []
    response_queue_length = get_queue_length()
    print(response_queue_length)
    for i in range(response_queue_length):
        response = sqs_client.receive_message(QueueUrl=response_queue.url)
        ans.append(response['Messages'][0]['Body'])
        sqs_client.delete_message(QueueUrl=response_queue.url, ReceiptHandle=response['Messages'][0]['ReceiptHandle'])
    return render_template('results.html', data=ans, data_length=response_queue_length)


@app.errorhandler(404)
def page_not_found(e):
    return "<h1>404</h1><p>The resource could not be found.</p>", 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
