try:
    import openai
    OPENAI_AVAILABLE = True
except Exception:
    openai = None
    OPENAI_AVAILABLE = False

# Do not hardcode API keys in source. A per-request OpenAI key is required for Auto-Validate.
OPENAI_API_KEY = None

def summarize_environment_data(environment_data):
    # Only include key metadata for each resource type
    # Ultra-summarize: limit to 1 item per resource type
    summary = {
        "subscriptions": environment_data.get("subscriptions", [])[:1],
        "vnets": [
            {
                "name": v.get("name"),
                "location": v.get("location"),
                "address_space": v.get("address_space", {}).get("address_prefixes", []),
                "resource_group_name": v.get("resource_group_name"),
                "tags": v.get("tags", {})
            } for v in environment_data.get("vnets", [])[:1]
        ],
        "subnets": [
            {
                "name": s.get("name"),
                "address_prefix": s.get("address_prefix"),
                "virtual_network_name": s.get("virtual_network_name"),
                "resource_group_name": s.get("resource_group_name"),
                "network_security_group": s.get("network_security_group", {}).get("id"),
                "route_table": s.get("route_table", {}).get("id"),
                "purpose": s.get("purpose", "")
            } for s in environment_data.get("subnets", [])[:1]
        ],
        "peerings": [
            {
                "name": p.get("name"),
                "virtual_network_name": p.get("virtual_network_name"),
                "allow_virtual_network_access": p.get("allow_virtual_network_access"),
                "allow_forwarded_traffic": p.get("allow_forwarded_traffic"),
                "use_remote_gateways": p.get("use_remote_gateways"),
                "allow_gateway_transit": p.get("allow_gateway_transit"),
                "peering_state": p.get("peering_state")
            } for p in environment_data.get("peerings", [])[:1]
        ],
        "route_tables": [
            {
                "name": rt.get("name"),
                "location": rt.get("location"),
                "resource_group_name": rt.get("resource_group_name"),
                "disable_bgp_route_propagation": rt.get("disable_bgp_route_propagation"),
                "routes": [
                    {
                        "name": r.get("name"),
                        "address_prefix": r.get("address_prefix"),
                        "next_hop_type": r.get("next_hop_type"),
                        "next_hop_ip_address": r.get("next_hop_ip_address")
                    } for r in rt.get("routes", [])[:1]
                ]
            } for rt in environment_data.get("route_tables", [])[:1]
        ]
    }
    return summary

def get_gpt5_network_explanation(environment_data, mode='report', api_key=None):
    """
    Generate an explanation from the LLM.
    mode='report' -> well-formatted technical report (gpt-4o)
    mode='opinion' -> architecture-level opinion using GPT-4 (fallback to gpt-4o if gpt-4 fails)
    """
    if not OPENAI_AVAILABLE:
        return "OpenAI SDK not installed on this host. Install the 'openai' package in a virtualenv and restart the app to enable LLM features."

    # Require a per-request api_key for security. Do NOT persist it.
    if not api_key:
        return "OpenAI API key is required for Auto-Validate. Please provide your personal OpenAI API key in the form and try again."
    openai.api_key = api_key
    summary = summarize_environment_data(environment_data)
    import json as _json

    # Build prompts for both modes
    if mode == 'opinion':
        prompt = (
            "You are an expert Azure cloud architect and technical reviewer. "
            "Provide a detailed architectural opinion of the following summarized Azure environment data. "
            "This is not just a technical inventory: critique the design, call out architectural trade-offs, risks, single points of failure, security concerns, operational gaps, and cost/scale implications. "
            "For each major area (Subscription, VNets, Subnets, Peerings, Route Tables, Gateways), explain the likely operational intent, identify what is well-designed, what is risky or could cause outages, and give prioritized, concrete recommendations and migration steps. "
            "Include estimated impact, suggested timeline (short/medium/long), and which teams should own remediation. Format as clear markdown with headings, callout bullets, and an executive summary under 'Overview'.\n\n"
            f"Environment Data Summary:\n{summary}"
        )
        # Use gpt-4o for opinion mode per user preference (higher quality + larger token budget)
        preferred_model = "gpt-4o"
        max_tokens = 900
    else:
        prompt = (
            "You are a professional Azure network architect. "
            "Given the following summarized Azure environment data in JSON, provide a visually appealing, well-formatted technical report in markdown. "
            "Use headings, bullet points, bold text, and clear sections for each network component (Subscription, VNets, Subnets, Peerings, Route Tables, Notable Configurations, Suggestions for Improvement). "
            "Highlight important findings and recommendations. Make the explanation easy to read and professional.\n\n"
            f"Environment Data Summary:\n{summary}"
        )
        preferred_model = "gpt-4o"
        max_tokens = 600

    prompt_str = str(prompt)
    if len(prompt_str) > 4000:
        return f"Warning: The environment data is too large to analyze. Please reduce the number of resources or select a smaller subscription.\nPrompt size: {len(prompt_str)} characters."

    # Try preferred model; no fallback to gpt-4 since user prefers gpt-4o
    try_models = [preferred_model]

    last_exception = None
    for model_name in try_models:
        try:
            response = openai.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=max_tokens
            )
            logger.info("OpenAI API raw response (%s): %s", model_name, _json.dumps(response.to_dict(), indent=2))
            content = None
            if response.choices:
                # Support both older and newer SDK shapes
                choice = response.choices[0]
                if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
                    content = choice.message.content
                elif hasattr(choice, 'text'):
                    content = choice.text

            if content:
                # If the model indicated it stopped due to length, request a single continuation
                finish_reason = None
                try:
                    # newer SDK shapes
                    finish_reason = response.choices[0].finish_reason
                except Exception:
                    try:
                        finish_reason = response.choices[0].get('finish_reason')
                    except Exception:
                        finish_reason = None

                if finish_reason == 'length':
                    try:
                        cont_prompt = "The previous response was truncated due to length. Continue the markdown report from where it left off, do not repeat earlier content, continue the same formatting and headings."
                        # Provide the tail of the previous content as context so the model can continue accurately
                        last_snippet = content[-2000:] if content else ""
                        # Provide the prior assistant content as an assistant message, then ask the model (as user) to continue directly from that end.
                        messages = [
                            {"role": "assistant", "content": last_snippet},
                            {"role": "user", "content": "The previous assistant message above is the end of the report — continue the markdown report immediately from that point, do not repeat earlier content, preserve headings and style."}
                        ]
                        cont_resp = openai.chat.completions.create(
                            model=model_name,
                            messages=messages,
                            max_completion_tokens= max(500, int(max_tokens/2))
                        )
                        logger.info("OpenAI continuation raw response (%s): %s", model_name, _json.dumps(cont_resp.to_dict(), indent=2))
                        # extract continuation text
                        cont_text = None
                        if cont_resp.choices:
                            c = cont_resp.choices[0]
                            if hasattr(c, 'message') and hasattr(c.message, 'content'):
                                cont_text = c.message.content
                            elif hasattr(c, 'text'):
                                cont_text = c.text
                        if cont_text:
                            content = content.rstrip() + "\n\n" + cont_text.lstrip()
                    except Exception:
                        logger.exception("Failed to fetch continuation from LLM")

                return content
            else:
                return f"No explanation found. Raw response:<br><pre>{_json.dumps(response.to_dict(), indent=2)}</pre>"
        except Exception as e:
            import traceback
            logger.error("OpenAI API error (%s): %s", model_name, traceback.format_exc())
            last_exception = e
            # try next model if available
            continue

    return f"Error generating explanation: {last_exception}"
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
import pdfkit
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

    # Normalize subscriptions for the dropdown
    raw_subs = data.get('subscriptions', [])
    subscriptions = []
    for sub in raw_subs:
        if isinstance(sub, (list, tuple)) and len(sub) >= 2:
            subscriptions.append({'id': sub[0], 'name': sub[1]})
        elif isinstance(sub, dict):
            subscriptions.append({'id': sub.get('subscription_id') or sub.get('id') or str(sub), 'name': sub.get('display_name') or sub.get('name') or str(sub)})
        else:
            subscriptions.append({'id': str(sub), 'name': str(sub)})

    # Normalize vnets for client-side filtering
    vnets = []
    for v in data.get('vnets', []):
        vnets.append({
            'name': v.get('name'),
            'subscription_id': v.get('subscription_id'),
            'resource_group_name': v.get('resource_group_name')
        })

    selected_subscription = None
    selected_vnet = None

    if request.method == 'POST':
        subscription_id = (request.form.get('subscription_id') or '').strip()
        vnet_name = (request.form.get('vnet_name') or '').strip()
        selected_subscription = subscription_id
        selected_vnet = vnet_name
        role = (request.form.get('role') or '').strip().lower()
        is_hub = (role == 'hub')
        is_spoke = (role == 'spoke')

        # Retrieve VNet peerings
        peerings = [peering for peering in data.get('peerings', []) if peering.get('virtual_network_name') == vnet_name and peering.get('subscription_id') == subscription_id]
        results = [{
            'peering_name': peering.get('name'),
            'allow_vnet_access': peering.get('allow_virtual_network_access'),
            'allow_forwarded_traffic': peering.get('allow_forwarded_traffic'),
            'use_remote_gateways': peering.get('use_remote_gateways'),
            'allow_gateway_transit': peering.get('allow_gateway_transit'),
            'remote_virtual_network': peering.get('remote_virtual_network', {}).get('id') if peering.get('remote_virtual_network') else None
        } for peering in peerings]

    return render_template('validate_hub_peerings.html', results=results, is_hub=is_hub, is_spoke=is_spoke, subscriptions=subscriptions, vnets=vnets, selected_subscription=selected_subscription, selected_vnet=selected_vnet)

@app.route('/auto-validate', methods=['GET', 'POST'])
def auto_validate():
    issues = None
    gpt_explanation = ""
    gpt_explanation_raw = ""
    data = environment_data
    subscriptions = data.get('subscriptions', [])
    selected_subscription_id = None

    if request.method == 'POST':
        import datetime
        # Selected subscription
        selected_subscription_id = request.form.get('subscription')
        # Filter data by selected subscription
        subnets = [s for s in data.get('subnets', []) if s.get('subscription_id') == selected_subscription_id]
        route_tables = [rt for rt in data.get('route_tables', []) if rt.get('subscription_id') == selected_subscription_id]
        nsgs = [n for n in data.get('nsgs', []) if n.get('subscription_id') == selected_subscription_id]
        # If you have a firewall IP to check, set it here; otherwise, use None or a default value
        firewall_ip = None
        issues = validate_routes(subnets, route_tables, nsgs, firewall_ip)

        # Prepare filtered data for LLM
        filtered_data = {
            "subscriptions": [sub for sub in subscriptions if sub[0] == selected_subscription_id],
            "vnets": [v for v in data.get('vnets', []) if v.get('subscription_id') == selected_subscription_id],
            "subnets": subnets,
            "route_tables": route_tables,
            "nsgs": nsgs,
            "peerings": [p for p in data.get('peerings', []) if p.get('subscription_id') == selected_subscription_id],
            "vnet_gateways": [g for g in data.get('vnet_gateways', []) if g.get('subscription_id') == selected_subscription_id],
            "express_route_circuits": [c for c in data.get('express_route_circuits', []) if c.get('subscription_id') == selected_subscription_id],
            "insights": []
        }

        # Read analysis mode from form (report or opinion)
        analysis_mode = request.form.get('analysis_mode', 'report')
        logger.info("Auto-validate requested for subscription %s with analysis mode: %s", selected_subscription_id, analysis_mode)
        # Read optional per-request OpenAI key from form (do not store)
        per_request_key = (request.form.get('openai_key') or '').strip() or None
        raw_explanation = get_gpt5_network_explanation(filtered_data, mode=analysis_mode, api_key=per_request_key) or ""

        # Attempt to detect likely truncation (very small last token) and request continuation before saving
        try:
            last_chunk = raw_explanation.strip()[-1:] if raw_explanation and len(raw_explanation.strip())>0 else ''
            # If the last character is a single alphabetic char or the last line is unusually short, try to continue
            need_cont = False
            if last_chunk.isalpha():
                need_cont = True
            else:
                lines = [l for l in raw_explanation.splitlines() if l.strip()]
                if lines:
                    last_line = lines[-1].strip()
                    if len(last_line) < 6 and not last_line.endswith(('.', ':')):
                        need_cont = True
            if need_cont:
                try:
                    cont_prompt = "The previous response you generated may have been truncated. Continue the markdown report from where it likely left off; do not repeat earlier content. Keep the same style."
                    cont_resp = openai.chat.completions.create(
                        model=preferred_model,
                        messages=[{"role":"user","content":cont_prompt}],
                        max_completion_tokens= int(max_tokens/2) if 'max_tokens' in locals() else 300
                    )
                    cont_text = None
                    if cont_resp.choices:
                        c = cont_resp.choices[0]
                        if hasattr(c, 'message') and hasattr(c.message, 'content'):
                            cont_text = c.message.content
                        elif hasattr(c, 'text'):
                            cont_text = c.text
                    if cont_text:
                        raw_explanation = raw_explanation.rstrip() + "\n\n" + cont_text.lstrip()
                        logger.info("Appended continuation to explanation before saving")
                except Exception:
                    logger.exception("Continuation attempt failed")
        except Exception:
            pass

        # Save raw markdown to autoValidations/auto_validate_<timestamp>_<mode>.md
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        md_path = f"autoValidations/auto_validate_{timestamp}_{analysis_mode}.md"
        try:
            os.makedirs('autoValidations', exist_ok=True)
            with open(md_path, "w") as f:
                f.write(raw_explanation)
        except Exception as e:
            logger.error(f"Failed to save markdown file: {e}")

        # Always read the .md file and render it as HTML for display
        try:
            import markdown
            import re
            with open(md_path, "r") as f:
                md_content = f.read()
            # Always extract the first code block if present
            code_block_match = re.search(r"```(?:markdown)?\s*([\s\S]*?)```", md_content)
            if code_block_match:
                extracted_md = code_block_match.group(1)
            else:
                extracted_md = md_content
            print("[DEBUG] Extracted markdown content:\n", extracted_md)
            # Post-process: convert inline code spans that contain letters into bold for readability
            try:
                import re as _re
                def _beautify_inline_code(s: str) -> str:
                    # Replace `text` with **text** only when text contains alphabetic characters (avoid IPs/CIDRs)
                    return _re.sub(r'`([^`]*[A-Za-z][^`]*)`', r'**\1**', s)
                extracted_md = _beautify_inline_code(extracted_md)
            except Exception:
                pass
            # Provide both raw markdown and server-side rendered HTML fallback
            gpt_explanation_raw = extracted_md
            gpt_explanation = markdown.markdown(extracted_md, extensions=['extra', 'tables', 'sane_lists'])
            print("[DEBUG] Rendered HTML:\n", gpt_explanation)
        except Exception:
            gpt_explanation_raw = raw_explanation
            try:
                import re as _re
                def _beautify_inline_code(s: str) -> str:
                    return _re.sub(r'`([^`]*[A-Za-z][^`]*)`', r'**\1**', s)
                raw_explanation = _beautify_inline_code(raw_explanation)
            except Exception:
                pass
            try:
                import markdown as _md
                gpt_explanation = _md.markdown(raw_explanation, extensions=['extra', 'tables', 'sane_lists'])
            except Exception:
                gpt_explanation = raw_explanation

    return render_template('auto_validate.html', issues=issues, gpt_explanation=gpt_explanation, gpt_explanation_raw=gpt_explanation_raw, subscriptions=subscriptions, selected_subscription_id=selected_subscription_id)

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


def compute_insights(data):
    """Return a list of insight dicts per subscription for the /insights page."""
    insights = []
    subscriptions = data.get('subscriptions', [])
    for sub in subscriptions:
        try:
            sub_id = sub[0]
            sub_name = sub[1] if len(sub) > 1 else sub_id
        except Exception:
            # If the subscriptions were stored as dicts or strings, fall back
            if isinstance(sub, dict):
                sub_id = sub.get('subscription_id') or sub.get('id') or str(sub)
                sub_name = sub.get('display_name') or sub.get('name') or sub_id
            else:
                sub_id = str(sub)
                sub_name = str(sub)

        total_vnets = len([v for v in data.get('vnets', []) if v.get('subscription_id') == sub_id])
        total_subnets = len([s for s in data.get('subnets', []) if s.get('subscription_id') == sub_id])
        total_nsgs = len([n for n in data.get('nsgs', []) if n.get('subscription_id') == sub_id])
        total_route_tables = len([rt for rt in data.get('route_tables', []) if rt.get('subscription_id') == sub_id])
        # Estimate subnets with BGP enabled by counting route tables that do not disable BGP propagation
        subnets_with_bgp = 0
        for rt in data.get('route_tables', []):
            if rt.get('subscription_id') == sub_id and not rt.get('disable_bgp_route_propagation'):
                subnets_with_bgp += 1

        total_peerings = len([p for p in data.get('peerings', []) if p.get('subscription_id') == sub_id])
        total_vnet_gateways = len([g for g in data.get('vnet_gateways', []) if g.get('subscription_id') == sub_id])
        total_express = len([e for e in data.get('express_route_circuits', []) if e.get('subscription_id') == sub_id])
        regions = sorted(list({v.get('location') for v in data.get('vnets', []) if v.get('subscription_id') == sub_id and v.get('location')}))

        insights.append({
            "Subscription Name": sub_name,
            "Total VNets": total_vnets,
            "Total Subnets": total_subnets,
            "Total NSGs": total_nsgs,
            "Total Route Tables": total_route_tables,
            "Subnets with BGP Enabled": subnets_with_bgp,
            "Total Peerings": total_peerings,
            "Total VNet Gateways": total_vnet_gateways,
            "Total ExpressRoute Circuits": total_express,
            "Regions": ", ".join(regions) if regions else "N/A"
        })

    return insights


@app.route('/insights', methods=['GET'])
def insights():
    """Render the insights page. If environment data is empty, the template shows a friendly empty state."""
    data = environment_data
    insights_list = []
    try:
        insights_list = compute_insights(data)
    except Exception:
        logger.exception("Failed to compute insights")
        insights_list = []
    return render_template('insights.html', insights=insights_list)

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
    # Configure pdfkit options if needed
    options = {
        'page-size': 'A4',
        'orientation': 'Landscape',
        'margin-top': '10mm',
        'margin-bottom': '10mm',
        'margin-left': '10mm',
        'margin-right': '10mm',
        'enable-local-file-access': None,  # Allow local file access for images/CSS
    }
    # If you see a permissions warning for /run/user/1000/, run this in your shell:
    # sudo chmod 700 /run/user/1000/
    pdf = pdfkit.from_string(rendered, False, options=options)
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=network_report.pdf'
    return response

if __name__ == '__main__':
    app.run(debug=True)