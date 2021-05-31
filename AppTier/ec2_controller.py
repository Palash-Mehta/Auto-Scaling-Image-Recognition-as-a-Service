# Import dependencies
print("IMPORTING DEPENDENCIES")
import time
import boto3
from botocore.exceptions import ClientError
from variables import ACCESS_KEY, SECRET_KEY, REGION, USERNAME, KEY_FILE, RESPONSE_QUEUE, REQUEST_QUEUE
import paramiko
import threading

print("<------ INITIALIZING AWS SERVICES ------>")
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
print("SQS initialized")

# Initialize EC2
ec2 = boto3.resource(
    'ec2',
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    region_name=REGION
)
ec2_client = boto3.client(
    'ec2',
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    region_name=REGION
)
print("EC2 initialized")
print("<----------------- DONE ----------------->")

# This array will store all instances that are busy processing the images
busy = []
# This array will store all instances that are in stopping state
stop = []
# At most 20 instances will be working due to free tier constraints
max_worker_instances = 20


# Gets and returns a queue having passed name
def get_queue(name):
    try:
        queue = sqs.get_queue_by_name(QueueName=name)
    except ClientError as error:
        print("Couldn't get queue named {}".format(name))
        raise error
    else:
        return queue


print('<------ GETTING REQUEST AND RESPONSE QUEUES ------>')
request_queue = get_queue(REQUEST_QUEUE)
response_queue = get_queue(RESPONSE_QUEUE)
print("Request queue URL {}".format(request_queue.url))
print("Request queue URL {}".format(response_queue.url))
print('<--------------------- DONE ---------------------->')

# The web tier and app tier controller instances will always be busy (running).
# So we will add the IP address of the instances to the busy array.
for ec2_instance in ec2.instances.all():
    try:
        for tag in ec2_instance.tags:
            if ('Name' in tag['Key']) and (tag['Value'] in ['Web-Tier', 'App-Tier-Controller']):
                busy.append(ec2_instance.public_ip_address)
    except TypeError:
        continue
print("Web-Tier Controller and App-Tier instance are now running and busy!")
print("<---------------------- EXECUTION HAS STARTED -------------------->")


# Deletes a message from the queue
def delete_message_from_queue(queue_url, receipt_handle):
    try:
        sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
    except ClientError as error:
        print("Couldn't delete message with receipt handle {}".format(receipt_handle))
        raise error
    else:
        return True


# Gets and returns the message from the queue
def get_message_from_queue(queue_url):
    try:
        response = sqs_client.receive_message(QueueUrl=queue_url)
    except ClientError as error:
        print("Cannot get a message from {}".format(queue_url))
        raise error
    else:
        return response


# Calculates and returns the length of the request queue
def get_request_queue_length():
    try:
        request_queue_dict = sqs_client.get_queue_attributes(
            QueueUrl=request_queue.url,
            AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
        )
        request_queue_length = int(request_queue_dict['Attributes']['ApproximateNumberOfMessages']) + \
                               int(request_queue_dict['Attributes']['ApproximateNumberOfMessagesNotVisible'])
    except ClientError as error:
        print("Cannot get a response from {}".format(REQUEST_QUEUE))
        raise error
    else:
        return request_queue_length


# Finds and returns the instance which is running but not busy i.e it is free.
def get_free_ec2_instances():
    running = []
    for instance in ec2.instances.all():
        if instance.state['Name'] == 'running':
            running.append(instance)

    # If no instances are running, simply return None
    if len(running) == 0:
        return None

    # Filter out instances from the running array that in stopping state or are busy
    for free_instance in running:
        free_ec2_ip_address = free_instance.public_ip_address
        if free_ec2_ip_address not in busy and free_ec2_ip_address not in stop:
            return free_instance
    return None


# Logic for launching and stopping EC2 instances based of request queue length
def ec2_shrink_grow():
    running = 0
    for instance in ec2.instances.all():
        if instance.state['Name'] == 'running' or instance.state['Name'] == 'pending':
            running += 1
    busy_instances = len(busy)
    available_instances = running - busy_instances
    request_queue_length = get_request_queue_length()
    # Logic for scale out
    if available_instances < request_queue_length:
        # We need to start new instances
        to_be_started = request_queue_length - available_instances
        if to_be_started <= 0:
            return
        stopped = []
        running = 0
        for instance in ec2.instances.all():
            if instance.state['Name'] == 'stopped':
                stopped.append(instance)
            elif instance.state['Name'] == 'running' or instance.state['Name'] == 'pending':
                running += 1

        for stopped_instance in stopped:
            if running == max_worker_instances:
                break
            ec2_client.start_instances(InstanceIds=[stopped_instance.instance_id])
            print("<------ IN GROWING PHASE ------>")
            print("Starting instance with ID: {}".format(stopped_instance.instance_id))
            running += 1
            to_be_started -= 1
            if to_be_started == 0:
                break
    # Logic for scale in
    elif available_instances > request_queue_length:
        # Instances need to be stopped
        to_be_stopped = available_instances - request_queue_length
        running = []
        if to_be_stopped <= 0:
            return
        time.sleep(5)
        for instance in ec2.instances.all():
            if instance.state['Name'] == 'running' or instance.state['Name'] == 'pending':
                running.append(instance)

        total_running_instances = len(running)
        if total_running_instances <= 2:
            return

        for running_instance in running:
            if running_instance.public_ip_address not in busy:
                stop.append(running_instance.public_ip_address)
                print("<------ IN SHRINKING PHASE ------>")
                print('Stopping instance with IP address: {0}'.format(running_instance.public_ip_address))
                ec2_client.stop_instances(InstanceIds=[running_instance.instance_id])
                total_running_instances -= 1
                to_be_stopped -= 1
                if to_be_stopped == 0:
                    break


# SSH into the the worker instances and execute remote classification script
def ssh_into_workers(instance, image_to_be_processed):
    ssh_private_key = paramiko.RSAKey.from_private_key_file(KEY_FILE)
    worker_instance = paramiko.SSHClient()
    worker_instance.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connected_to_client = False
    # Keep trying connecting to the instance until connection is established
    while not connected_to_client:
        try:
            worker_instance.connect(hostname=instance.public_ip_address, username=USERNAME, pkey=ssh_private_key)
        except Exception as e:
            connected_to_client = False
        else:
            connected_to_client = True

    # Once the connection is established, execute the script
    command = "cd classifier && python3 ec2_workers.py " + image_to_be_processed
    (stdin, stdout, stderr) = worker_instance.exec_command(command)
    stdin.flush()

    # If exit status is 0, means our script was successfully executed
    if stdout.channel.recv_exit_status() == 0:
        print("{} was done processing".format(image_to_be_processed))

    # Processing was done, so we remove the instance from the busy array
    busy.remove(instance.public_ip_address)
    # Close the connection
    worker_instance.close()
    # Check again for resource scaling
    ec2_shrink_grow()


while True:
    # Get the message from the request queue
    message = get_message_from_queue(request_queue.url)
    # If at all the response has any message, then scale the resource
    if message.get('Messages'):
        # Get the image name from the resource
        image = message['Messages'][0]['Body']
        print("Image name received from SQS queue is {}".format(image))
        instance_for_process = get_free_ec2_instances()

        while not instance_for_process:
            time.sleep(3)
            ec2_shrink_grow()
            instance_for_process = get_free_ec2_instances()
        busy.append(instance_for_process.public_ip_address)
        print(
            "Image {} is assigned to instance with ip address {}".format(image, instance_for_process.public_ip_address))
        # Assign image to a free instance and add the instance to the busy array
        # Message is received so delete it from the request queue
        delete_message_from_queue(request_queue.url, message['Messages'][0]['ReceiptHandle'])
        thread = threading.Thread(target=ssh_into_workers, args=(instance_for_process, image))
        thread.start()
    else:
        # There might not be new messages but some messages prior are yet to be processed, so continue resource scaling
        ec2_shrink_grow()
        time.sleep(4)
