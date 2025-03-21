import boto3
import time
import os
import subprocess
from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Label, Static, Input, Select
from textual import on
from textual.containers import VerticalScroll, Horizontal
from textual.widgets import Button

lightsail_client = boto3.client('lightsail')
ec2_client = boto3.client('ec2')

LIGHTSAIL_INSTANCES = []
LIGHTSAIL_DATABASES = []
EC2_INSTANCES = []

def fetch_running_ec2_instances():
    global EC2_INSTANCES
    response = ec2_client.describe_instances(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'stopped']}]
    )
    instances = []
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']
            instance_state = instance['State']['Name']
            name = next((tag['Value'] for tag in instance.get('Tags', []) if tag['Key'] == 'Name'), 'N/A')
            public_ip = instance.get('PublicIpAddress', 'N/A')
            tags = [tag['Key'] for tag in instance.get('Tags', [])]
            instances.append((instance_id, name, instance_state, public_ip, tags))
    return instances


def fetch_lightsail_instances():
    global LIGHTSAIL_INSTANCES
    response = lightsail_client.get_instances()
    instances = []
    instance_names = []
    for instance in response['instances']:
        instance_name = instance['name']
        instance_state = instance['state']['name']
        public_ip = instance['publicIpAddress'] if 'publicIpAddress' in instance else 'N/A'
        tags = [tag.get('key') for tag in instance.get('tags', []) if 'key' in tag] 
        instances.append((instance_name, instance_name, instance_state, public_ip, tags))
        instance_names.append(instance_name)
    return instances, instance_names


def fetch_lightsail_databases():
    response = lightsail_client.get_relational_databases()
    instances = []
    db_names = []
    for db_instance in response['relationalDatabases']:
        db_instance_id = db_instance['name']
        db_instance_state = db_instance['state']
        tags = [tag.get('key') for tag in db_instance.get('tags', []) if 'key' in tag]
        instances.append((db_instance_id, db_instance_id, db_instance_state, 'N/A', tags))
        db_names.append(db_instance_id)
    return instances, db_names

def check_instance_ports(self, instance_name):
    try:
        response = self.lightsail_client.get_instance(instanceName=instance_name)
        public_ports = response['instance']['publicPorts']
        
        print(f"Current public ports for {instance_name}: {public_ports}")
        return public_ports
    except Exception as e:
        print(f"Error fetching public ports for {instance_name}: {e}")
        
def check_lightsail_ports(self, instance_name):
    try:
        response = self.lightsail_client.get_instance(instanceName=instance_name)
        public_ports = response['instance']['publicPorts']
        print(f"Current public ports for {instance_name}: {public_ports}")
        return public_ports
    except Exception as e:
        print(f"Error fetching public ports for {instance_name}: {e}")


class IpModal(ModalScreen):
    def __init__(self, instance_id, instance_type, apply_ip_callback, add_port_callback):
        super().__init__()
        self.instance_id = instance_id
        self.instance_type = instance_type
        self.apply_ip_callback = apply_ip_callback
        self.add_port_callback = add_port_callback

    def compose(self) -> ComposeResult:
        yield Label(f"Manage IPs and Ports for instance {self.instance_id}", id="ip-label")
        self.port_input = Input(placeholder="Enter Port (e.g., 80)", id="port-input")
        yield self.port_input
        yield Button("Detach IP", id="detach-ip-button", classes="button-show-all")
        yield Button("Create and Attach IP", id="create-attach-ip-button", variant="primary", classes="button-launch-instance")
        yield Button("Add Port", id="add-port-button", variant="primary")
        yield Button("Cancel", id="cancel-ip-button")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        port_value = self.port_input.value.strip()
        if event.button.id == "detach-ip-button":
            await self.apply_ip_callback(self.instance_id, None, "detach")
        elif event.button.id == "create-attach-ip-button":
            await self.apply_ip_callback(self.instance_id, None, "create_and_attach")
        elif event.button.id == "add-port-button":
            if port_value.isdigit():
                port = int(port_value)
                await self.add_port_callback(self.instance_id, self.instance_type, port)
            else:
                self.notify("Invalid port value. Please enter a valid number.")
        elif event.button.id == "cancel-ip-button":
            self.dismiss()

class LaunchLightsailModal(ModalScreen):
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

    def compose(self):
        yield Static("Launch Lightsail Instance", classes="modal-title")
        yield Label("Instance Name:")
        self.instance_name_input = Input(placeholder="Enter instance name")
        yield self.instance_name_input

        yield Label("SSH Key Name (optional):")
        self.ssh_key_input = Input(placeholder="Enter key name or leave blank for default")
        yield self.ssh_key_input

        yield Label("Select Pricing Plan:")
        self.pricing_select = Select(
            [
                ("$5 - 512MB RAM, 2 vCPUs, 20GB SSD, 512GB Transfer", "nano_3_1"),
                ("$7 - 1GB RAM, 2 vCPUs, 40GB SSD, 1TB Transfer", "micro_2_0"),
                ("$12 - 2GB RAM, 2 vCPUs, 60GB SSD, 1.5TB Transfer", "small_2_0"),
                ("$24 - 4GB RAM, 2 vCPUs, 80GB SSD, 2TB Transfer", "medium_2_0"),
                ("$44 - 8GB RAM, 2 vCPUs, 160GB SSD, 2.5TB Transfer", "large_2_0"),
                ("$84 - 16GB RAM, 4 vCPUs, 320GB SSD, 3TB Transfer", "xlarge_2_0"),
                ("$164 - 32GB RAM, 8 vCPUs, 640GB SSD, 3.5TB Transfer", "2xlarge_2_0"),
                ("$384 - 64GB RAM, 16 vCPUs, 1280GB SSD, 4TB Transfer", "4xlarge_2_0"),
            ],
            prompt="Choose a pricing plan"
        )
        yield self.pricing_select

        yield Button("Launch", id="launch-lightsail",variant="success", classes="button-show-all")
        yield Button("Cancel", id="cancel-lightsail", variant="error", classes="button-launch-instance")

    def on_button_pressed(self, event):
        if event.button.id == "launch-lightsail":
            instance_name = self.instance_name_input.value.strip()
            ssh_key = self.ssh_key_input.value.strip()
            selected_plan_id = self.pricing_select.value

            print("Launching Lightsail Instance...")
            print(f"Instance Name: {instance_name}")
            print(f"SSH Key: {ssh_key}")
            print(f"Selected Plan: {selected_plan_id}")

            if not instance_name or not selected_plan_id:
                print("Instance name and pricing plan selection are required!")
                return

            self.parent_app.launch_lightsail_instance(instance_name, selected_plan_id)
            self.dismiss()

        elif event.button.id == "cancel-lightsail":
            print("Lightsail launch canceled.")
            self.dismiss()




class LaunchInstanceModal(ModalScreen):
    def __init__(self, on_launch: callable):
        super().__init__()
        self.on_launch = on_launch
        self.ami_id_value = "ami-00bb6a80f01f03502"
        self.instance_name = Input(placeholder="Enter Instance Name")

        self.instance_type_select = Select(
            [
                ("t2.nano - 1 vCPU, 0.5GB RAM - $0.0062/hr", "t2.nano"),
                ("t2.micro - 1 vCPU, 1GB RAM - $0.0124/hr", "t2.micro"),
                ("t2.small - 1 vCPU, 2GB RAM - $0.0248/hr", "t2.small"),
                ("t2.medium - 2 vCPU, 4GB RAM - $0.0496/hr", "t2.medium"),
                ("t2.large - 2 vCPU, 8GB RAM - $0.0992/hr", "t2.large"),
                ("t2.xlarge - 4 vCPU, 16GB RAM - $0.1984/hr", "t2.xlarge"),
                ("t2.2xlarge - 8 vCPU, 32GB RAM - $0.3968/hr", "t2.2xlarge"),
                ("t3.nano - 2 vCPU, 0.5GB RAM - $0.0056/hr", "t3.nano"),
                ("t3.micro - 2 vCPU, 1GB RAM - $0.0112/hr", "t3.micro"),
                ("t3.small - 2 vCPU, 2GB RAM - $0.0224/hr", "t3.small"),
                ("t3.medium - 2 vCPU, 4GB RAM - $0.0448/hr", "t3.medium"),
                ("t3.large - 2 vCPU, 8GB RAM - $0.0896/hr", "t3.large"),
                ("t3.xlarge - 4 vCPU, 16GB RAM - $0.1792/hr", "t3.xlarge"),
                ("t3.2xlarge - 8 vCPU, 32GB RAM - $0.3584/hr", "t3.2xlarge"),
            ],
            prompt="Choose an instance type"
        )

        self.key_pair = Input(placeholder="Enter Key Pair Name")
        self.volume_size = Input(placeholder="Enter Volume Size (GB)")

    def compose(self) -> None:
        yield Label("Launch EC2 Instance")
        yield Label(f"AMI ID: {self.ami_id_value}")
        yield self.instance_name
        yield Label("Select Instance Type:")
        yield self.instance_type_select
        yield self.key_pair
        yield self.volume_size
        yield Button("Launch", id="launch-button", classes="button-show-all")
        yield Button("Cancel", id="cancel-button", classes="button-launch-instance")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "launch-button":
            instance_name = self.instance_name.value.strip()
            instance_type = self.instance_type_select.value
            key_pair = self.key_pair.value.strip()
            volume_size = self.volume_size.value.strip()

            if not instance_name or not instance_type:
                print("Instance Name and Instance Type are required!")
                return

            await self.on_launch(self.ami_id_value, instance_name, instance_type, key_pair, volume_size)
            self.app.pop_screen()

        elif event.button.id == "cancel-button":
            self.app.pop_screen()


class ConfirmationModal(ModalScreen):
    def __init__(self, action, instance_id, apply_action_callback):
        super().__init__()
        self.action = action
        self.instance_id = instance_id
        self.apply_action_callback = apply_action_callback

    def compose(self) -> ComposeResult:
        yield Label(f"Are you sure you want to {self.action} instance {self.instance_id}?", id="confirm-label")
        yield Button(f"Yes, {self.action}", id="confirm-yes-button", classes="button-show-all")
        yield Button("No, cancel", id="confirm-no-button", classes="button-launch-instance")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes-button":
            await self.apply_action_callback(self.instance_id)
            self.dismiss()
        elif event.button.id == "confirm-no-button":
            self.dismiss()


class TagModal(ModalScreen):
    def __init__(self, instance_id, apply_tag_callback):
        super().__init__()
        self.instance_id = instance_id
        self.apply_tag_callback = apply_tag_callback

    def compose(self) -> ComposeResult:
        yield Label(f"Add a tag to instance {self.instance_id}", id="tag-label")
        self.tag_input = Input(placeholder="Enter tag value", id="tag-input")
        yield self.tag_input
        yield Button("Apply", id="apply-tag-button", classes="button-show-all")
        yield Button("Cancel", id="cancel-tag-button", classes="button-launch-instance")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-tag-button":
            tag = self.tag_input.value.strip()
            if tag:
                await self.apply_tag_callback(self.instance_id, tag)
            self.dismiss()
        elif event.button.id == "cancel-tag-button":
            self.dismiss()
            
class LightsailSSHManager:
    def __init__(self):
        self.instances = self.get_instances() 
        self.pem_file_path = '/Users/vgts/Desktop/AWS_UI/ansible-runner.pem'

    def get_instances(self):  
        response = self.client.get_instances()
        instances = []
        for instance in response['instances']:
            instance_id = instance['instanceId']
            name = instance['name']
            state = instance['state']['name']
            public_ip = None

            for ip in instance['publicIpAddresses']:
                public_ip = ip

            tags = instance.get('tags', [])
            instances.append((instance_id, name, state, public_ip, tags))
        return instances


class AwsStatusApp(App):
    def __init__(self):
        super().__init__()
        self.lightsail_client = boto3.client('lightsail')
        self.ec2_client = boto3.client('ec2')
        
    CSS = """
    Screen {
        layout: vertical;
    }

    Button {
        margin-left: 0;
        height: 3;
        align: right middle;
    }

    Grid {
        padding: 0 0 0 0;
        width: 100%;
        height: 100%; 
        overflow-y: auto;
        overflow-x: auto;
        # scrollbar-size: 1 2;
    }

    .instance-box {
        text-align: center;
        text-style: bold italic underline;
        # color: #0052D4;
        color: #FFFFFF;
        width: 40%;
        margin-left: 46;
        text-style: bold;
        padding-bottom: 0;
        border: solid;
        height: auto;
        background: #222222;
    }

    .bg-color-0 {
        # margin-left: 146;
        margin-bottom: 1;
        # width: 96%;
        background: rgb(106, 6, 156);
        # background: #FFFFFF;
    }

    .bg-color-1 {
        margin-bottom: 1;
        # width: 48%;
        background: #ba8b02;
        # background: rgb(156, 6, 96);
    }

    .bg-color-2 {
        margin-bottom: 1;
        # margin-left: 146;
        # width: 96%;
        # background: #FFFFFF;
        background: rgb(204, 132, 24);
    }

    .bg-color-3 {
        margin-bottom: 1;
        # width: 48%;
        # background: #FFFFFF;
        background: rgb(141, 156, 6);
    }

    .bg-color-4 {
        margin-bottom: 1;
        # margin-left: 146;
        # width: 96%;
        # background: #3d72b4;
        background: rgb(6, 156, 151);
    }

    .bg-color-5 {
        margin-bottom: 1;
        # width: 48%;
        # background: #FFFFFF;
        background: rgb(4, 125, 224);
    }

    Header {
        background: #4c9f70;
        text-style: bold;
        color: white;
        height: 3;
        align: center middle;
    }

    Footer {
        background: #4c9f70;
        color: white;
        height: 3;
        align: center middle;
    }

    #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: 1fr 3;
        padding: 0 1;
        width: 60;
        height: 11;
        border: thick $background 80%;
        background: $surface;
    }

    #info {
        column-span: 2;
        height: 1fr;
        width: 1fr;
        content-align: center middle;
    }
    
    .button-show-all {
        column-span: 1;
        background: #4CAF50;  
        color: white;
    }

    .button-launch-instance {
        background: #008CBA; 
        color: white;
    }

    .button-launch-lightsail {
        background: #f44336; 
        color: white;
    }
    .button-start {
        # background: #4CAF50;
        background: #536976; 
        color: white;
    }

    .button-stop {
        # background: #f44336; 
        background: #74ebd5; 
        color: white;
    }

    .button-reboot {
        background: #ff9800; 
        color: white;
    }

    .button-tag {
        background: #2196F3; 
        color: white;
    }

    .button-ip {
        background: #9C27B0; 
        color: white;
    }
    
    Button {
        color: black;
        # background: #FFFDE4;
        background: #ff4b1f;
        width: 10%;
        # margin-bottom: 1;
    }
    """

    def compose(self) -> None:  
            yield Header()
            yield Button("Show All Instances", id="show-all-button", classes="button-show-all")
            yield Button("EC2 Instance", id="launch-instance-button", classes="button-launch-instance")
            yield Button("Lightsail", id="launch-lightsail-button", classes="button-launch-lightsail")
            self.instances_grid = Grid()
            self.instances_grid.styles.layout = "vertical"
            yield self.instances_grid
            yield Footer()


    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "show-all-button":
            ec2_instances = fetch_running_ec2_instances()
            lightsail_instances, self.LIGHTSAIL_INSTANCES = fetch_lightsail_instances()
            lightsail_databases, self.LIGHTSAIL_DATABASES = fetch_lightsail_databases()

            self.instances = [
                *ec2_instances,
                *lightsail_instances,
                *lightsail_databases,
            ]

            self.display_instances(self.instances)
            
        elif event.button.id == "launch-lightsail-button":
            modal = LaunchLightsailModal(self)
            self.push_screen(modal)

        elif event.button.id == "launch-instance-button":
            modal = LaunchInstanceModal(self.create_ec2_instance)
            self.push_screen(modal)

        elif event.button.id.startswith("start-"):
            instance_id = event.button.id.split("-", 1)[1]
            await self.show_confirmation_modal("start", instance_id, self.start_instance)

        elif event.button.id.startswith("stop-"):
            instance_id = event.button.id.split("-", 1)[1]
            await self.show_confirmation_modal("stop", instance_id, self.stop_instance)

        elif event.button.id.startswith("reboot-"):
            instance_id = event.button.id.split("-", 1)[1]
            await self.show_confirmation_modal("reboot", instance_id, self.reboot_instance)

        elif event.button.id.startswith("tag-"):
            instance_id = event.button.id.split("-", 1)[1]
            await self.show_confirmation_modal("Add Tag", instance_id, self.show_tag_modal)
            # await self.show_tag_modal(instance_id)

        elif event.button.id.startswith("ip-"):
            instance_id = event.button.id.split("-", 1)[1]
            await self.show_confirmation_modal("IP Management", instance_id, self.show_ip_modal)
            # await self.show_ip_modal(instance_id)
            
        elif event.button.id.startswith("ssh-"):
                instance_id = event.button.id.split("-", 1)[1]
                await self.open_ssh_connection(instance_id)

    async def open_ssh_connection(self, instance_id: str):
        instance = next((i for i in self.instances if i[0] == instance_id), None)
        if instance:
            _, _, state, public_ip, _ = instance
            if state == "running":
                pem_file = f"/Users/vgts/Desktop/AWS_UI/demo.pem"
                if not os.path.exists(pem_file):
                    self.notify(f"Error: PEM file '{pem_file}' not found. Make sure it's in the correct directory.")
                    return
                ssh_command = f"ssh -i {pem_file} ubuntu@{public_ip}"
                print(f"Opening SSH session to {public_ip} in a new Terminal window...")

                subprocess.run(["osascript", "-e", f'tell app "Terminal" to do script "{ssh_command}"'])
            else:
                self.notify("Instance is not running. Unable to open SSH.")
            
    async def show_confirmation_modal(self, action: str, instance_id: str, apply_action_callback):
        modal = ConfirmationModal(action, instance_id, apply_action_callback)
        self.push_screen(modal)

    async def show_ip_modal(self, instance_id: str):
        modal = IpModal(
            instance_id,
            "ec2" if instance_id.startswith("i-") else "lightsail",
            self.manage_ip,  
            self.manage_port
        )
        self.push_screen(modal)

    async def show_tag_modal(self, instance_id: str):
        modal = TagModal(instance_id, self.apply_tag_to_instance)
        self.push_screen(modal)
        
    async def add_tag_to_instance(self, instance_id: str, tag_key: str, instance_type: str):
        try:
            if instance_type == "ec2":
                ec2_client.create_tags(
                    Resources=[instance_id],
                    Tags=[{"Key": tag_key, "Value": ""}],
                )
                self.notify(f"Tag '{tag_key}' added to EC2 instance {instance_id}.")
            elif instance_type == "lightsail":
                lightsail_client.tag_resource(
                    resourceName=instance_id,
                    tags=[{"key": tag_key, "value": ""}],
                )
                self.notify(f"Tag '{tag_key}' added to Lightsail instance {instance_id}.")
        except Exception as e:
            self.notify(f"Error adding tag: {str(e)}")

    async def start_instance(self, instance_id: str):
        try:
            if instance_id.startswith("i-"):  
                ec2_client.start_instances(InstanceIds=[instance_id])
                self.notify(f"EC2 instance {instance_id} started.")
            elif instance_id in self.LIGHTSAIL_INSTANCES:  
                lightsail_client.start_instance(instanceName=instance_id)
                self.notify(f"Lightsail instance {instance_id} started.")
            elif instance_id in self.LIGHTSAIL_DATABASES:  
                lightsail_client.start_relational_database(relationalDatabaseName=instance_id)
                self.notify(f"Lightsail database {instance_id} started.")
        except Exception as e:
            self.notify(f"Error starting instance {instance_id}: {str(e)}")

    async def stop_instance(self, instance_id: str):
        try:
            if instance_id.startswith("i-"):  
                ec2_client.stop_instances(InstanceIds=[instance_id])
                self.notify(f"EC2 instance {instance_id} stopped.")
            elif instance_id in self.LIGHTSAIL_INSTANCES:  
                lightsail_client.stop_instance(instanceName=instance_id)
                self.notify(f"Lightsail instance {instance_id} stopped.")
            elif instance_id in self.LIGHTSAIL_DATABASES:  
                lightsail_client.stop_relational_database(relationalDatabaseName=instance_id)
                self.notify(f"Lightsail database {instance_id} stopped.")
        except Exception as e:
            self.notify(f"Error stopping instance {instance_id}: {str(e)}")

    async def reboot_instance(self, instance_id: str):
        try:
            if instance_id.startswith("i-"):  
                ec2_client.reboot_instances(InstanceIds=[instance_id])
                self.notify(f"EC2 instance {instance_id} rebooted.")
            elif instance_id in self.LIGHTSAIL_INSTANCES: 
                response = lightsail_client.reboot_instance(instanceName=instance_id)
                operation_id = response['operations'][0]['id'] 
                
                while True:
                    operation_response = lightsail_client.get_operations()
                   
                    operation = next((op for op in operation_response['operations'] if op['id'] == operation_id), None)
                    if operation:
                        status = operation['status']
                        if status == 'Succeeded':
                            self.notify(f"Lightsail instance {instance_id} rebooted successfully.")
                            break
                        elif status == 'Failed':
                            self.notify(f"Reboot operation failed for Lightsail instance {instance_id}.")
                            break
                        else:
                            time.sleep(5)
                    else:
                        time.sleep(5)

            elif instance_id in self.LIGHTSAIL_DATABASES:  
                response = lightsail_client.reboot_relational_database(relationalDatabaseName=instance_id)
                operation_id = response['operations'][0]['id']

                while True:
                    operation_response = lightsail_client.get_operations()
                   
                    operation = next((op for op in operation_response['operations'] if op['id'] == operation_id), None)
                    if operation:
                        status = operation['status']
                        if status == 'Succeeded':
                            self.notify(f"Lightsail database {instance_id} rebooted successfully.")
                            break
                        elif status == 'Failed':
                            self.notify(f"Reboot operation failed for Lightsail database {instance_id}.")
                            break
                        else:
                            time.sleep(5)
                    else:
                        time.sleep(5)
        except Exception as e:
            self.notify(f"Error rebooting instance {instance_id}: {str(e)}")
    
    async def apply_tag_to_instance(self, instance_id: str, tag: str):
        try:
            if instance_id.startswith("i-"): 
                ec2_client.create_tags(Resources=[instance_id], Tags=[{"Key": tag, "Value": tag}])
                self.notify(f"Tag '{tag}' applied to EC2 instance {instance_id}")

            elif instance_id in self.LIGHTSAIL_INSTANCES:  
                lightsail_client.tag_resource(
                    resourceName=instance_id,
                    tags=[{"key": tag, "value": "Environment"}]
                )
                self.notify(f"Tag '{tag}' applied to Lightsail instance {instance_id}")

            elif instance_id in self.LIGHTSAIL_DATABASES: 
                lightsail_client.tag_resource(
                    resourceName=instance_id,
                    tags=[{"key": tag, "value": "Environment"}]
                )
                self.notify(f"Tag '{tag}' applied to Lightsail database {instance_id}")

        except Exception as e:
            self.notify(f"Error applying tag to {instance_id}: {str(e)}")
            
    def get_static_ip_name(self, ip: str) -> str:
        """
        Retrieves the static IP name associated with a given IP address.
        """
        try:
            
            response = lightsail_client.get_static_ips()
            static_ips = response.get("staticIps", [])

            for static_ip in static_ips:
                if static_ip["ipAddress"] == ip:
                    return static_ip["name"] 
                
            return None
        except Exception as e:
            self.notify(f"Error retrieving static IP name for {ip}: {str(e)}")
            return None

    def detach_elastic_ip_by_instance(self, instance_id: str):
        try:
            response = ec2_client.describe_addresses(Filters=[{
                'Name': 'instance-id',
                'Values': [instance_id]
            }])

            addresses = response.get("Addresses", [])
            
            if addresses:
                for address in addresses:
                    association_id = address.get("AssociationId")
                    if association_id:
                        ec2_client.disassociate_address(AssociationId=association_id)
                        self.notify(f"Elastic IP {address['PublicIp']} successfully detached from EC2 instance {instance_id}.")
                    else:
                        self.notify(f"Elastic IP {address['PublicIp']} is not associated with EC2 instance {instance_id}.")
            else:
                self.notify(f"No Elastic IP found attached to EC2 instance {instance_id}.")

        except Exception as e:
            self.notify(f"Error detaching Elastic IP from EC2 instance '{instance_id}': {str(e)}")

    def detach_static_ip_by_instance(self, instance_name: str):
        try:
            response = lightsail_client.get_static_ips()
            static_ips = response.get("staticIps", [])
            static_ip_to_detach = None
            for static_ip in static_ips:
                if static_ip.get("attachedTo") == instance_name:
                    static_ip_to_detach = static_ip["name"]
                    break

            if static_ip_to_detach:
               
                lightsail_client.detach_static_ip(staticIpName=static_ip_to_detach)
                self.notify(f"Static IP '{static_ip_to_detach}' successfully detached from instance '{instance_name}'.")
            else:
              
                self.notify(f"No static IP is attached to the instance '{instance_name}'.")
        except Exception as e:
            self.notify(f"Error detaching Static IP from instance '{instance_name}': {str(e)}")
            
    def get_security_group_id(self, instance_id):
        try:
            response = ec2_client.describe_instances(InstanceIds=[instance_id])
            security_groups = response["Reservations"][0]["Instances"][0]["SecurityGroups"]
            return [sg["GroupId"] for sg in security_groups]
        except Exception as e:
            print(f"Error retrieving security groups: {e}")
            return []


    def add_ipv4_rule(self, security_group_id, protocol, port_range, cidr_block):
        try:
            self.ec2_client.authorize_security_group_ingress(
                GroupId=security_group_id,
                IpPermissions=[
                    {
                        "IpProtocol": protocol,
                        "FromPort": port_range[0],
                        "ToPort": port_range[1],
                        "IpRanges": [{"CidrIp": cidr_block}],
                    }
                ],
            )
            print(f"Successfully added rule to security group {security_group_id}")
        except Exception as e:
            print(f"Error adding rule: {e}")


    def add_lightsail_ipv4_rule(self, instance_name, protocol, port_range, cidr_block):
        try:
            response = self.lightsail_client.open_instance_public_ports(
                portInfo={
                    "fromPort": port_range[0],
                    "toPort": port_range[1],
                    "protocol": protocol,
                    "cidrs": [cidr_block],
                },
                instanceName=instance_name,
            )
            
            print(f"API response: {response}")
            
            print(f"Port {port_range[0]}-{port_range[1]} rule added successfully to Lightsail instance {instance_name}.")
            
            instance_details = self.lightsail_client.get_instance(instanceName=instance_name)
            public_ports = instance_details["instance"]["networking"]["ports"]
            print(f"Current public ports for {instance_name}: {public_ports}")
            
        except Exception as e:
            print(f"Error adding port rule to Lightsail instance {instance_name}: {e}")
            if hasattr(e, "response"):
                print(f"Full error response: {e.response}")

    def create_or_get_key_pair(self, key_name: str) -> str:
        try:
            self.ec2_client.describe_key_pairs(KeyNames=[key_name])
            print(f"Key pair '{key_name}' already exists. Using the existing key pair.")
            return key_name 
        except self.ec2_client.exceptions.ClientError as e:
            if "InvalidKeyPair.NotFound" in str(e):
              
                print(f"Creating new key pair '{key_name}'.")
                key_pair = self.ec2_client.create_key_pair(KeyName=key_name)
                private_key = key_pair['KeyMaterial']
              
                save_path = f"/Users/vgts/Downloads/{key_name}.pem"
              
                try:
                    with open(save_path, 'w') as key_file:
                        key_file.write(private_key)

                    os.chmod(save_path, 0o400)

                    print(f"Key pair '{key_name}' created and private key saved to '{save_path}'.")
                except Exception as file_error:
                    print(f"Error saving private key to file: {file_error}")
                    raise
                return key_name
            else:
                print(f"Error checking or creating key pair: {e}")
                raise


    async def manage_ip(self, instance_id: str, ip: str, action: str, port: int = None):
        try:
            if action == "create_and_attach":
                if instance_id in self.LIGHTSAIL_INSTANCES:
                    static_ip_name = f"{instance_id}-ip"

                    try:
                        self.notify(f"Allocating a new static IP: {static_ip_name}...")
                        response = lightsail_client.allocate_static_ip(staticIpName=static_ip_name)
                        static_ip = response["staticIp"]["ipAddress"]
                        self.notify(f"New Static IP {static_ip} allocated successfully.")
                    except lightsail_client.exceptions.InvalidInputException as e:
                        if "already in use" in str(e):
                            self.notify(f"Static IP {static_ip_name} already exists. Proceeding to attach...")
                        else:
                            raise

                    self.notify(f"Attaching Static IP {static_ip_name} to {instance_id}...")
                    lightsail_client.attach_static_ip(
                        staticIpName=static_ip_name, instanceName=instance_id
                    )
                    self.notify(f"Static IP {static_ip_name} successfully attached to {instance_id}.")
                else:
                    self.notify("Checking for existing Elastic IPs...")
                    addresses = ec2_client.describe_addresses()["Addresses"]
                    detached_ip = None

                    for address in addresses:
                        if "InstanceId" not in address: 
                            detached_ip = address["PublicIp"]
                            break
                        elif address.get("InstanceId") == instance_id:
                            self.notify(f"Elastic IP {address['PublicIp']} is already attached to {instance_id}.")
                            return

                    if detached_ip:
                        self.notify(f"Found a detached Elastic IP: {detached_ip}. Attaching it to {instance_id}...")
                        ec2_client.associate_address(InstanceId=instance_id, PublicIp=detached_ip)
                        self.notify(f"Elastic IP {detached_ip} successfully attached to EC2 instance {instance_id}.")
                    else:
                        try:
                            self.notify("No detached Elastic IPs available. Allocating a new Elastic IP...")
                            response = ec2_client.allocate_address(Domain="vpc")
                            elastic_ip = response["PublicIp"]
                            self.notify(f"New Elastic IP {elastic_ip} allocated.")

                            self.notify(f"Attaching Elastic IP {elastic_ip} to {instance_id}...")
                            ec2_client.associate_address(InstanceId=instance_id, PublicIp=elastic_ip)
                            self.notify(f"Elastic IP {elastic_ip} created and attached to EC2 instance {instance_id}.")
                        except ec2_client.exceptions.ClientError as e:
                            if "AddressLimitExceeded" in str(e):
                                self.notify("Elastic IP limit exceeded. Unable to allocate a new IP.")
                            else:
                                raise


            elif action == "attach":
                if instance_id.startswith("i-"):
                    try:
                        ec2_client.describe_addresses(PublicIps=[ip])
                        ec2_client.associate_address(InstanceId=instance_id, PublicIp=ip)
                        self.notify(f"Elastic IP {ip} attached to EC2 instance {instance_id}.")
                    except ec2_client.exceptions.ClientError as e:
                        if "InvalidIPAddress" in str(e):
                            self.notify(f"Elastic IP {ip} does not exist.")
                        else:
                            raise
                elif instance_id in self.LIGHTSAIL_INSTANCES:
                    try:
                        lightsail_client.get_static_ip(staticIpName=ip)
                        lightsail_client.attach_static_ip(
                            staticIpName=ip, instanceName=instance_id
                        )
                        self.notify(f"Static IP {ip} attached to Lightsail instance {instance_id}.")
                    except lightsail_client.exceptions.ClientError as e:
                        if "NotFoundException" in str(e):
                            self.notify(f"Static IP {ip} does not exist.")
                        else:
                            raise

            elif action == "detach":
                if instance_id.startswith("i-"):
                    try:
                        self.notify(f"Detaching Elastic IP from EC2 instance {instance_id}...")
                        self.detach_elastic_ip_by_instance(instance_id=instance_id)  
                    except Exception as e:
                        self.notify(f"Error during detachment of Elastic IP from EC2 instance {instance_id}: {str(e)}")

                elif instance_id in self.LIGHTSAIL_INSTANCES:  
                    try:
                        self.detach_static_ip_by_instance(instance_name=instance_id)
                        self.notify(f"Static IP successfully detached from Lightsail instance {instance_id}.")
                    except Exception as e:
                        self.notify(f"Error during detachment of Static IP from Lightsail instance {instance_id}: {str(e)}")
                    
        except Exception as e:
            self.notify(f"Error managing IP for {instance_id}: {str(e)}")

    async def manage_port(self, instance_id: str, instance_type: str, port: int):
        try:
            protocol = "tcp"
            cidr_block = "0.0.0.0/0"

            if instance_type == "ec2":
                security_groups = self.get_security_group_id(instance_id)
                if security_groups:
                    for sg_id in security_groups:
                        self.add_ipv4_rule(sg_id, protocol, (port, port), cidr_block)  
                    self.notify(f"Port {port} rule added to EC2 instance {instance_id}.")
                else:
                    self.notify(f"No security groups found for EC2 instance {instance_id}.")
            elif instance_type == "lightsail":
                self.add_lightsail_ipv4_rule(instance_id, protocol, (port, port), cidr_block)
                self.notify(f"Port {port} rule added to Lightsail instance {instance_id}.")
            else:
                self.notify(f"Unknown instance type for adding port rule: {instance_id}")
        except Exception as e:
            self.notify(f"Error adding port {port} for {instance_id}: {str(e)}")
            
    async def create_ec2_instance(self, ami_id, instance_name, instance_type, key_name, volume_size):
        try:
            key_name = self.create_or_get_key_pair(key_name)

            response = self.ec2_client.run_instances(
                ImageId=ami_id,
                InstanceType=instance_type,
                MinCount=1,
                MaxCount=1,
                KeyName=key_name,
                TagSpecifications=[
                    {
                        'ResourceType': 'instance',
                        'Tags': [{'Key': 'Name', 'Value': instance_name}]
                    }
                ],
                BlockDeviceMappings=[
                    {
                        'DeviceName': '/dev/sda1',
                        'Ebs': {
                            'VolumeSize': int(volume_size),
                            'VolumeType': 'gp2',
                        }
                    }
                ]
            )

            instance_id = response['Instances'][0]['InstanceId']
            print(f"EC2 instance '{instance_name}' created successfully with ID: {instance_id}")
            return instance_id
        except Exception as e:
            print(f"Error creating EC2 instance: {e}")
            return None

    def launch_lightsail_instance(self, instance_name, selected_plan_id):
        try:
            blueprint_id = "ubuntu_20_04"  
            bundle_id = selected_plan_id

            client = boto3.client("lightsail", region_name="ap-south-1")
            
            response = client.create_instances(
                instanceNames=[instance_name],
                availabilityZone="ap-south-1a",
                blueprintId=blueprint_id,
                bundleId=bundle_id, 
                userData="""#!/bin/bash
                echo "Hello, Lightsail!" > /home/ubuntu/hello.txt
                """, 
                ipAddressType="ipv4",
            )
            
            print(f"Instance Creation Response: {response}")
            print(f"Lightsail instance '{instance_name}' created successfully!")

        except Exception as e:
            print(f"Error creating Lightsail instance: {e}")

    
    def display_instances(self, instances):
        for child in self.instances_grid.children:
            self.instances_grid.remove(child)

        for index, (instance_id, name, state, public_ip, tags) in enumerate(instances):
            tags_display = ", ".join(tags) if tags else "No Tags" 
            content = (
                f"Instance ID: {instance_id}\n"
                f"Name: {name}\n"
                f"State: {state}\n"
                f"Public IP: {public_ip}\n"
                f"Tags: {tags_display}"
            )
            background_class = f"bg-color-{index % 6}"
            box = Static(content, classes=f"instance-box {background_class}")
            self.instances_grid.mount(box)

            start_button = Button("Start", id=f"start-{instance_id}", classes="button-start")
            stop_button = Button("Stop", id=f"stop-{instance_id}", classes="button-stop")
            reboot_button = Button("Reboot", id=f"reboot-{instance_id}", classes="button-reboot")
            tag_button = Button("Tag", id=f"tag-{instance_id}", classes="button-tag")
            ip_button = Button("IP", id=f"ip-{instance_id}", classes="button-ip")
            ssh_button = Button("SSH", id=f"ssh-{instance_id}")

            box.mount(start_button)
            box.mount(stop_button)
            box.mount(reboot_button)
            box.mount(tag_button)
            box.mount(ip_button)
            box.mount(ssh_button)
            
            if state == "running" or state == "available":
                start_button.disabled = True
                stop_button.disabled = False
            else:
                start_button.disabled = False
                stop_button.disabled = True

            ssh_button.disabled = state != "running"
            ip_button.disabled = state != "running" 
            tag_button.disabled = state != "running"

            print(f"Mounted SSH Button: ssh-{instance_id}") 
if __name__ == "__main__":
    app = AwsStatusApp()
    app.run()
