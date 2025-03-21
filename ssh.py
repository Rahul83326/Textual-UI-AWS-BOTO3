import boto3
import subprocess
import platform
import os

client = boto3.client('lightsail')

response = client.get_instances()
instance_name = 'ubuntu-Test'
instance = next((i for i in response['instances'] if i['name'] == instance_name), None)

if instance:
    public_ip = instance['publicIpAddress']
    pem_file = "/Users/vgts/Desktop/AWS_UI/Test-lightsail.pem"

    if not os.path.exists(pem_file):
        print(f"Error: PEM file '{pem_file}' not found. Make sure it's in the correct directory.")
    else:
        ssh_command = f"ssh -i {pem_file} ubuntu@{public_ip}"
        print(f"Opening SSH session to {public_ip} in a new Terminal window...")

        if platform.system() == "Darwin":
            subprocess.run(["osascript", "-e", f'tell app "Terminal" to do script "{ssh_command}"'])
else:
    print(f"Instance '{instance_name}' not found.")
