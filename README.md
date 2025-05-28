# 🌐 Welcome

This application is designed to help you validate your **Virtual Network (VNet)** routes and peerings in **Azure**.

Whether you're managing a complex network infrastructure or just getting started, this tool provides the insights you need to ensure your network is configured correctly.

**Author:** andlopes@microsoft.com
<br> Improvements need to be done in the tool, but I see a lot of potential for new features not only for route tables but many other services in Azure as well.

---

## 🚀 Features

- 🔍 Validate VNet peerings to ensure proper connectivity.
- 📊 Gain insights into your network configuration, including VNets, subnets, NSGs, and route tables.
    - This helps you validated everything quickly in one single place.
- 🛠️ Check BGP propagation and route configurations.
- 💾 Download a report if you need.
    - The download is a bit unstable in terms of structure of what should be in the report, it generates but need to be improved.

---

## 🛠️ Installation

1. **Create a virtual environment: ( Optional step )**

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

2. **Install the required dependencies:**

    ```bash
    pip install Flask azure-identity azure-mgmt-network azure-mgmt-resource tabulate
    ```

3. **Set up Azure authentication:**

    - Ensure you have the Azure CLI installed and logged in.
    - Run `az login` to authenticate.
    - The tool will use azure cli to load your environment details data.

4. **Run the application:**

    ```bash
    python3 app.py
    ```
    or use "nohup" syntax "&" to run in background mode.
    ```bash
    nohup python3 app.py &
    ```    

---

## 📦 Dependencies

- **Flask** – A micro web framework for Python.
- **azure-identity** – Azure SDK for Python to authenticate with Azure.
- **azure-mgmt-network** – Azure SDK for Python to manage network resources.
- **azure-mgmt-resource** – Azure SDK for Python to manage resource groups and resources.
- **tabulate** – A library to format tabular data.

---

## 📋 Usage

Navigate to `http://127.0.0.1:5000/` in your web browser.

- Click on **Load environment** to generate a .json file with your environment's data
    - This .json will be stored under .environments/ directory. 
- Select a subscription from the dropdown menu and click **Submit** to view VNets and their details.
- Use the **"Validate Hub Peerings"** menu option to validate peerings for a specific VNet.

---

I hope you find this tool helpful in managing your Azure network infrastructure.  
If you have any questions or need support, feel free to reach me out!
