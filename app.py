"""
Author: Anderson Lopes
Date: December 11, 2024
Description: This Flask web application validates Virtual Network (VNet) routes and hub peerings in Azure. It uses Azure SDKs to list subscriptions, VNets, subnets, route tables, and network security groups (NSGs). The app displays the validation results in a web interface, leveraging Bootstrap for styling and Flask for backend integration.

Features:
- List all Azure subscriptions.
- Select a subscription to view its VNets and subnets.
- Display route tables and BGP propagation status for each subnet.
- Display associated NSGs for each subnet.
- Validate hub peerings for a selected VNet.

Installation:
1. Create a virtual environment:
    python -m venv venv
    source venv/bin/activate  

2. Install the required dependencies:
    pip install Flask azure-identity azure-mgmt-network azure-mgmt-resource tabulate

3. Set up Azure authentication:
    - Ensure you have the Azure CLI installed and logged in.
    - Run `az login` to authenticate.

4. Run the application:
    python3 app.py

Dependencies:
- Flask: A micro web framework for Python.
- azure-identity: Azure SDK for Python to authenticate with Azure.
- azure-mgmt-network: Azure SDK for Python to manage network resources.
- azure-mgmt-resource: Azure SDK for Python to manage resource groups and resources.
- tabulate: A library to format tabular data.

Usage:
- Navigate to `http://127.0.0.1:5000/` in your web browser.
- Select a subscription from the dropdown menu and click "Submit" to view VNets and their details.
- Use the "Validate Hub Peerings" menu option to validate peerings for a specific VNet.
"""

from flask import Flask, render_template, request, send_file, make_response
from weasyprint import HTML, CSS
from azure.identity import DefaultAzureCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import SubscriptionClient
from tabulate import tabulate
from azure.mgmt.resource import ResourceManagementClient  # Import the ResourceManagementClient
import json
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your_secret_key'

@app.route('/', methods=['GET', 'POST'])
def index():

    return render_template('index.html')

# Global variable to store the environment data
environment_data = {}

def load_environment_data():
    global environment_data
    os.makedirs('environments', exist_ok=True)
    file_path = 'environments/environment_data.json'
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            try:
                environment_data = json.load(f)
            except json.JSONDecodeError:
                environment_data = {}  # Initialize with an empty dictionary if the file is empty or invalid
    else:
        environment_data = {}  # Clear the global variable if the file doesn't exist

# Load the environment data when the application starts
load_environment_data()

@app.route('/load-environment', methods=['POST'])
def load_environment():
    credential = DefaultAzureCredential()
    subscription_client = SubscriptionClient(credential)

    # Fetch data from Azure
    subscriptions = list(subscription_client.subscriptions.list())
    data = {
        "subscriptions": [(sub.subscription_id, sub.display_name) for sub in subscriptions],
        "vnets": [],
        "subnets": [],
        "route_tables": [],
        "nsgs": [],
        "peerings": [],
        "vnet_gateways": [],
        "express_route_circuits": [],
        "insights": []
    }

    for sub in subscriptions:
        subscription_id = sub.subscription_id
        network_client = NetworkManagementClient(credential, subscription_id)
        resource_client = ResourceManagementClient(credential, subscription_id)

        # Fetch VNets, subnets, route tables, NSGs, peerings, VNet gateways, and ExpressRoute circuits
        vnets = list(network_client.virtual_networks.list_all())
        for vnet in vnets:
            vnet_data = vnet.as_dict()
            vnet_data["subscription_id"] = subscription_id
            vnet_data["resource_group_name"] = vnet.id.split('/')[4]
            data["vnets"].append(vnet_data)
            subnets = list(network_client.subnets.list(resource_group_name=vnet_data["resource_group_name"], virtual_network_name=vnet.name))
            for subnet in subnets:
                subnet_data = subnet.as_dict()
                subnet_data["subscription_id"] = subscription_id
                subnet_data["resource_group_name"] = vnet_data["resource_group_name"]
                subnet_data["virtual_network_name"] = vnet.name
                data["subnets"].append(subnet_data)
                if subnet.route_table:
                    try:
                        route_table_id = subnet.route_table.id.split('/')[-1]
                        route_table_rg = subnet.route_table.id.split('/')[4]
                        route_table = network_client.route_tables.get(resource_group_name=route_table_rg, route_table_name=route_table_id)
                        route_table_data = route_table.as_dict()
                        route_table_data["subscription_id"] = subscription_id
                        route_table_data["resource_group_name"] = route_table_rg
                        data["route_tables"].append(route_table_data)
                    except Exception as e:
                        logger.error(f"Error fetching route table {subnet.route_table.id}: {e}")
                if subnet.network_security_group:
                    try:
                        nsg_id = subnet.network_security_group.id.split('/')[-1]
                        nsg_rg = subnet.network_security_group.id.split('/')[4]
                        nsg = network_client.network_security_groups.get(resource_group_name=nsg_rg, network_security_group_name=nsg_id)
                        nsg_data = nsg.as_dict()
                        nsg_data["subscription_id"] = subscription_id
                        nsg_data["resource_group_name"] = nsg_rg
                        data["nsgs"].append(nsg_data)
                    except Exception as e:
                        logger.error(f"Error fetching NSG {subnet.network_security_group.id}: {e}")
            peerings = list(network_client.virtual_network_peerings.list(resource_group_name=vnet_data["resource_group_name"], virtual_network_name=vnet.name))
            for peering in peerings:
                peering_data = peering.as_dict()
                peering_data["subscription_id"] = subscription_id
                peering_data["resource_group_name"] = vnet_data["resource_group_name"]
                peering_data["virtual_network_name"] = vnet.name
                data["peerings"].append(peering_data)

            # Fetch VNet gateways
            vnet_gateways = list(network_client.virtual_network_gateways.list(resource_group_name=vnet_data["resource_group_name"]))
            for gateway in vnet_gateways:
                gateway_data = gateway.as_dict()
                gateway_data["subscription_id"] = subscription_id
                gateway_data["resource_group_name"] = vnet_data["resource_group_name"]
                data["vnet_gateways"].append(gateway_data)

        # Fetch ExpressRoute circuits
        resource_groups = list(resource_client.resource_groups.list())
        for rg in resource_groups:
            express_route_circuits = list(network_client.express_route_circuits.list(resource_group_name=rg.name))
            for circuit in express_route_circuits:
                circuit_data = circuit.as_dict()
                circuit_data["subscription_id"] = subscription_id
                circuit_data["resource_group_name"] = rg.name
                data["express_route_circuits"].append(circuit_data)

    # Save data to JSON file
    os.makedirs('environments', exist_ok=True)
    with open('environments/environment_data.json', 'w') as f:
        json.dump(data, f, indent=4)  # Pretty-print the JSON data

    # Reload the environment data
    load_environment_data()

    message = "Environment data loaded successfully!"
    return render_template('index.html', message=message)

@app.route('/routes', methods=['GET', 'POST'])
def routes():
    data = environment_data
    subscriptions = data.get("subscriptions", [])
    results = []
    selected_subscription_id = None

    if request.method == 'POST':
        selected_subscription_id = request.form.get('subscription')
        # Process the selected subscription
        for vnet in data.get("vnets", []):
            if vnet["subscription_id"] == selected_subscription_id:
                vnet_name = vnet["name"]
                vnet_prefixes = ", ".join(vnet["address_space"]["address_prefixes"])
                vnet_rg = vnet["resource_group_name"]

                for subnet in data.get("subnets", []):
                    if subnet["virtual_network_name"] == vnet_name and subnet["resource_group_name"] == vnet_rg:
                        subnet_name = subnet["name"]
                        subnet_prefix = subnet.get("address_prefix", "N/A")
                        route_table_name = "None"
                        route_table_content = "No routes"
                        bgp_propagation = "Unknown"
                        if subnet.get("route_table"):
                            try:
                                route_table = next(rt for rt in data.get("route_tables", []) if rt["id"] == subnet["route_table"]["id"] and rt["subscription_id"] == selected_subscription_id)
                                route_table_name = route_table["name"]
                                bgp_propagation = "Disabled" if route_table["disable_bgp_route_propagation"] else "Enabled"
                                if route_table.get("routes"):
                                    nested_table = tabulate(
                                        [[route["name"], route["address_prefix"], route["next_hop_type"], route.get("next_hop_ip_address", "N/A")]
                                         for route in route_table["routes"]],
                                        headers=["Name", "Address Prefix", "Next Hop Type", "Next Hop IP"],
                                        tablefmt="plain"
                                    )
                                    route_table_content = nested_table
                            except StopIteration:
                                logger.error(f"Route table {subnet['route_table']['id']} not found for subscription {selected_subscription_id}")
                        nsg_name = "None"
                        if subnet.get("network_security_group"):
                            try:
                                nsg = next(nsg for nsg in data.get("nsgs", []) if nsg["id"] == subnet["network_security_group"]["id"] and nsg["subscription_id"] == selected_subscription_id)
                                nsg_name = nsg["name"]
                            except StopIteration:
                                logger.error(f"NSG {subnet['network_security_group']['id']} not found for subscription {selected_subscription_id}")
                        results.append([f"{vnet_name}<br><strong>{vnet_prefixes}</strong>", f"{subnet_name}<br><strong>{subnet_prefix}</strong>", route_table_name, bgp_propagation, route_table_content, nsg_name])

    return render_template('routes.html', results=results, subscriptions=subscriptions, selected_subscription_id=selected_subscription_id)

@app.route('/validate-hub-peerings', methods=['GET', 'POST'])
def validate_hub_peerings():
    data = environment_data
    results = []
    is_hub = False
    is_spoke = False
    if request.method == 'POST':
        subscription_id = request.form['subscription_id']
        vnet_name = request.form['vnet_name']
        is_hub = 'is_hub' in request.form
        is_spoke = 'is_spoke' in request.form
        # Retrieve VNet peerings
        peerings = [peering for peering in data.get("peerings", []) if peering["virtual_network_name"] == vnet_name and peering["subscription_id"] == subscription_id]
        results = [{
            'peering_name': peering["name"],
            'allow_vnet_access': peering["allow_virtual_network_access"],
            'allow_forwarded_traffic': peering["allow_forwarded_traffic"],
            'use_remote_gateways': peering["use_remote_gateways"],
            'allow_gateway_transit': peering["allow_gateway_transit"],
            'remote_virtual_network': peering["remote_virtual_network"]["id"]
        } for peering in peerings]
    return render_template('validate_hub_peerings.html', results=results, is_hub=is_hub, is_spoke=is_spoke)

@app.route('/insights', methods=['GET'])
def insights():
    data = environment_data
    insights_data = []

    for sub in data.get("subscriptions", []):
        subscription_id = sub[0]
        subscription_name = sub[1]
        total_vnets = 0
        total_subnets = 0
        total_nsgs = 0
        total_route_tables = 0
        subnets_with_bgp_enabled = 0
        total_peerings = 0
        total_vnet_gateways = 0
        total_express_route_circuits = 0
        regions = set()

        for vnet in data.get("vnets", []):
            if vnet["subscription_id"] == subscription_id:
                total_vnets += 1
                regions.add(vnet["location"])
                vnet_rg = vnet["resource_group_name"]
                for subnet in data.get("subnets", []):
                    if subnet["virtual_network_name"] == vnet["name"] and subnet["resource_group_name"] == vnet_rg:
                        total_subnets += 1
                        if subnet.get("network_security_group"):
                            total_nsgs += 1
                        if subnet.get("route_table"):
                            total_route_tables += 1
                            try:
                                route_table = next(rt for rt in data.get("route_tables", []) if rt["id"] == subnet["route_table"]["id"] and rt["subscription_id"] == subscription_id)
                                if not route_table["disable_bgp_route_propagation"]:
                                    subnets_with_bgp_enabled += 1
                            except StopIteration:
                                logger.error(f"Route table {subnet['route_table']['id']} not found for subscription {subscription_id}")
                peerings = [peering for peering in data.get("peerings", []) if peering["virtual_network_name"] == vnet["name"] and peering["resource_group_name"] == vnet_rg]
                total_peerings += len(peerings)

        # Count all unique VNet gateways within the subscription
        unique_gateways = {gateway["id"]: gateway for gateway in data.get("vnet_gateways", []) if gateway["subscription_id"] == subscription_id}
        total_vnet_gateways += len(unique_gateways)

        express_route_circuits = [circuit for circuit in data.get("express_route_circuits", []) if circuit["subscription_id"] == subscription_id]
        total_express_route_circuits += len(express_route_circuits)

        insights_data.append({
            "Subscription Name": subscription_name,
            "Total VNets": total_vnets,
            "Total Subnets": total_subnets,
            "Total NSGs": total_nsgs,
            "Total Route Tables": total_route_tables,
            "Subnets with BGP Enabled": subnets_with_bgp_enabled,
            "Total Peerings": total_peerings,
            "Total VNet Gateways": total_vnet_gateways,
            "Total ExpressRoute Circuits": total_express_route_circuits,
            "Regions": len(regions)
        })

    return render_template('insights.html', insights=insights_data)

@app.route('/auto-validate', methods=['GET', 'POST'])
def auto_validate():
    issues = None
    if request.method == 'POST':
        hub_subscription_id = request.form['subscription_id']
        hub_firewall_ip = request.form['firewall_ip']

        # Load the environment data from the JSON file
        data = environment_data

        # Filter the spoke subscriptions
        spoke_subscriptions = [sub for sub in data.get("subscriptions", []) if sub[0] != hub_subscription_id]

        # Filter the VNets, subnets, route tables, and NSGs based on the spoke subscriptions
        vnets = [vnet for vnet in data.get("vnets", []) if vnet["subscription_id"] in [sub[0] for sub in spoke_subscriptions]]
        subnets = [subnet for subnet in data.get("subnets", []) if subnet["virtual_network_name"] in [vnet["name"] for vnet in vnets]]
        route_tables = [rt for rt in data.get("route_tables", []) if rt["id"] in [subnet["route_table"]["id"] for subnet in subnets if "route_table" in subnet]]
        nsgs = [nsg for nsg in data.get("nsgs", []) if nsg["id"] in [subnet["network_security_group"]["id"] for subnet in subnets if "network_security_group" in subnet]]

        # Perform validation
        issues = validate_routes(subnets, route_tables, nsgs, hub_firewall_ip)

    return render_template('auto_validate.html', issues=issues)

def validate_routes(subnets, route_tables, nsgs, firewall_ip):
    issues = []

    for route_table in route_tables:
        for route in route_table["routes"]:
            if route["next_hop_type"] == 'VirtualAppliance' and route.get("next_hop_ip_address") != firewall_ip:
                issues.append({
                    "subscription": route_table["subscription_id"],
                    "route_table_name": route_table["name"],
                    "route_name": route["name"],
                    "description": f"has an incorrect next hop IP address: {route.get('next_hop_ip_address')}"
                })

    # Add more validation checks as needed

    return issues

@app.route('/pretty-json')
def pretty_json():
    file_path = 'environments/environment_data.json'
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            try:
                data = json.load(f)
                pretty_json = json.dumps(data, indent=4)
                return f"<pre>{pretty_json}</pre>"
            except json.JSONDecodeError:
                return "Error: Invalid JSON data"
    else:
        return "Error: JSON file not found"

@app.route('/download-json')
def download_json():
    file_path = 'environments/environment_data.json'
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name='environment_data.json')
    else:
        return "Error: JSON file not found"
    
@app.route('/generate-report', methods=['GET'])
def generate_report():
    data = environment_data
    return render_template('report.html', data=data)

@app.route('/download-report', methods=['GET'])
def download_report():
    data = environment_data
    rendered = render_template('report.html', data=data)
    pdf = HTML(string=rendered).write_pdf(stylesheets=[CSS(string='@page { size: A4 landscape; margin: 1cm; }')])
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=network_report.pdf'
    return response

if __name__ == '__main__':
    app.run(debug=True)