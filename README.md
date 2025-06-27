# Looker SFTP Action with Modern Key Support (Ed25519/ECDSA)

This Looker Action allows users to schedule and send Looker Looks and Dashboards to an SFTP server using modern and highly secure cryptographic keys, specifically Ed25519 and ECDSA. It leverages Google Cloud Functions for serverless execution and Google Cloud Secret Manager for secure storage of private keys.

This action is built to enhance security by moving away from older RSA keys towards more contemporary and robust elliptic curve cryptography (ECC) based keys.

## Table of Contents

- [Key Features](#key-features)
- [Why Ed25519 and ECDSA are More Secure than RSA](#why-ed25519-and-ecdsa-are-more-secure-than-rsa)
- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Setup Instructions](#setup-instructions)
  - [1. Prepare Your SSH Key](#1-prepare-your-ssh-key)
  - [2. Store Private Key in Google Cloud Secret Manager](#2-store-private-key-in-google-cloud-secret-manager)
  - [3. Deploy Cloud Functions](#3-deploy-cloud-functions)
    - [A. `action_list` Function](#a-action_list-function)
    - [B. `action_form` Function](#b-action_form-function)
    - [C. `action_execute` Function](#c-action_execute-function)
  - [4. Add Action to Looker](#4-add-action-to-looker)
- [Usage](#usage)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Key Features

*   **Secure Data Delivery:** Send Looker content (Looks, Dashboards) directly to your SFTP server.
*   **Modern Cryptography:** Natively supports Ed25519 and ECDSA keys for enhanced security.
*   **Secure Key Management:** Private keys are stored securely in Google Cloud Secret Manager.
*   **Serverless Architecture:** Utilizes Google Cloud Functions, eliminating the need to manage servers.
*   **Easy Integration:** Seamlessly integrates with the Looker Action Hub.
  
## Why Ed25519 and ECDSA are More Secure than RSA

Ed25519 (an EdDSA signature scheme using Curve25519) and ECDSA (Elliptic Curve Digital Signature Algorithm) are based on Elliptic Curve Cryptography (ECC). They offer significant security advantages over RSA, especially at comparable key sizes:

1.  **Stronger Security with Smaller Keys:**
    *   ECC provides the same level of security as RSA but with much smaller key sizes. For example, a 256-bit ECC key offers comparable security to a 3072-bit RSA key.
    *   **Benefits:**
        *   **Faster Computations:** Smaller keys mean faster key generation, signing, and verification operations, reducing computational overhead.
        *   **Reduced Bandwidth & Storage:** Smaller keys and signatures consume less bandwidth and storage.

2.  **Higher Security Per Bit:**
    *   The mathematical problem underlying ECC (the Elliptic Curve Discrete Logarithm Problem - ECDLP) is considered harder to solve than the integer factorization problem that RSA relies on, for a given key size. This means ECC can achieve higher security levels more efficiently.

3.  **Resistance to Certain Attacks:**
    *   **Ed25519 (EdDSA):** Is particularly noteworthy for its design features that help prevent common implementation pitfalls.
        *   **Deterministic Signatures:** EdDSA typically generates signatures deterministically, eliminating risks associated with poor randomness in nonce generation (a known vulnerability for some DSA/ECDSA implementations if not handled carefully).
        *   **Side-Channel Attack Resistance:** The design of Curve25519 and the EdDSA algorithms aims for better resistance against side-channel attacks.
    *   **ECDSA:** While older than Ed25519, it's still a significant improvement over RSA. Modern implementations and careful parameter selection make it very secure.

4.  **Modern Design and Scrutiny:**
    *   ECC algorithms, especially newer ones like Ed25519, have been designed with lessons learned from decades of cryptographic research and attack analysis on older systems like RSA.

In summary, choosing Ed25519 or ECDSA means you're using more efficient, modern cryptographic algorithms that provide robust security with better performance characteristics than traditional RSA, especially as desired security levels increase.

## Architecture Overview

1.  **User Action in Looker:** A Looker user schedules a Look or Dashboard to be sent via SFTP.
2.  **Looker Action Hub:** Looker communicates with the registered custom action.
    *   It first calls the `action_list` Cloud Function to identify the action.
    *   Then, it calls the `action_form` Cloud Function to get the dynamic form fields (e.g., SFTP server, username, path).
3.  **User Fills Form:** The user provides SFTP server details and other parameters in the Looker UI.
4.  **Execute Action:** Looker calls the `action_execute` Cloud Function with the data payload and form parameters.
5.  **`action_execute` Function:**
    *   Retrieves the SFTP private key from Google Cloud Secret Manager.
    *   Rstablish a secure SFTP connection using the Ed25519/ECDSA key.
    *   Streams the data from Looker to the specified path on the SFTP server.
6.  **Secret Manager:** Stores the PEM-encoded private key securely. Only the `action_execute` Cloud Function's service account needs permission to access it.

## Prerequisites

*   A Google Cloud Platform (GCP) project with billing enabled.
*   `gcloud` CLI installed and configured.
*   A Looker instance with admin access to add Action Hub actions.
*   An SFTP server configured to accept connections using an Ed25519 or ECDSA public key.
*   An Ed25519 or ECDSA private key in PEM format.

## Setup Instructions

### 1. Prepare Your SSH Key

If you don't already have an Ed25519 or ECDSA key pair:

*   **For Ed25519 (recommended):**
    ```bash
    ssh-keygen -t ed25519 -f ./my_looker_sftp_key -C "looker-sftp-action-key"
    ```
*   **For ECDSA (e.g., nistp521):**
    ```bash
    ssh-keygen -t ecdsa -b 521 -f ./my_looker_sftp_key -C "looker-sftp-action-key"
    ```

This will generate `my_looker_sftp_key` (private key) and `my_looker_sftp_key.pub` (public key).

**Important:**
*   Add the contents of `my_looker_sftp_key.pub` to the `authorized_keys` file on your SFTP server for the user you intend to connect as.
*   The private key `my_looker_sftp_key` **must be in PEM format**. If `ssh-keygen` generated it in the newer OpenSSH format, convert it:
    ```bash
    ssh-keygen -p -m PEM -f ./my_looker_sftp_key
    ```
    (You might be prompted for a passphrase; you can leave it empty if the key is not already passphrase-protected and you don't want to add one now for use with Secret Manager).

### 2. Store Private Key in Google Cloud Secret Manager

1.  Go to the [Secret Manager page](https://console.cloud.google.com/security/secret-manager) in the Google Cloud Console.
2.  Click **"Create Secret"**.
3.  **Name:** Enter a descriptive name (e.g., `looker-sftp-private-key`). Note this name.
4.  **Secret value:** Paste the entire content of your PEM-formatted private key file (e.g., `sftp`).
5.  Leave other settings as default and click **"Create secret"**.
6.  Once created, click on the secret name. You'll need its **Resource ID** (looks like `projects/YOUR_PROJECT_ID/secrets/YOUR_SECRET_NAME/versions/latest`). Copy this.

### 3. Deploy Cloud Functions

You will deploy three separate Cloud Functions. Clone this repository and navigate to the respective function directories for deployment.

**Note on Entry Points:** The `--entry-point` flag in the `gcloud` commands below should match the main Python function defined in each respective `main.py` file within the Cloud Function's directory. For example, if your `action_list_function/main.py` defines `def my_list_handler(request):`, then your entry point is `my_list_handler`. The names `action_list`, `action_form`, and `action_execute_main` (or similar) are common conventions. **Please verify the exact entry point function names from the source code files.**

*(Assuming the Python files are structured with entry points named `action_list`, `action_form`, and `handle_execution` respectively, as per common Looker Action patterns. Adjust if your source code differs.)*

**Parameters for `gcloud functions deploy`:**
*   `export PROJECT_ID`: Your Google Cloud Project ID.
*   `export YOUR_REGION=us-central1`: The GCP region for deployment (e.g., `us-central1`).
*   `export PYTHON_RUNTIME=python3111`: e.g., `python311`, `python312`.
*   `export PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format="value(projectNumber)")`
*   export LOOKER_ACTION_HUB_SECRET` Your secret you generated which allows Looker to authenticate to the Cloud function. You will also place this in Looker when you add your action. 
  
### A. `action_list` Function

This function tells Looker about the existence of your action.

```bash
# Navigate to the directory containing the action_list function code
# cd path/to/looker_sftp_action/

gcloud functions deploy actionlist \
  --project=YOUR_PROJECT_ID \
  --region=YOUR_REGION \
  --runtime=PYTHON_RUNTIME \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars=REGION=$REGION \
  --set-env-vars=PROJECT_ID=$PROJECT_ID \
  --set-env-vars=LOOKER_ACTION_HUB_SECRET=$LOOKER_ACTION_HUB_SECRET \
  --set-env-vars=PROJECT_NUMBER=$PROJECT_NUMBER \
  --entry-point=action_list
# Verify this entry point from the Python source
```

Make a note of the HTTPS Trigger URL for this function.

### B. action_form Function
This function provides Looker with the form fields needed to configure the SFTP action (e.g., hostname, username, path).


```bash
# Navigate to the directory containing the action_form function code
# cd path/to/looker_sftp_action/

gcloud functions deploy actionform \
  --project=YOUR_PROJECT_ID \
  --region=YOUR_REGION \
  --runtime=PYTHON_RUNTIME \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars=REGION=$REGION \
  --set-env-vars=PROJECT_ID=$PROJECT_ID \
  --set-env-vars=LOOKER_ACTION_HUB_SECRET=$LOOKER_ACTION_HUB_SECRET \
  --set-env-vars=PROJECT_NUMBER=$PROJECT_NUMBER \
  --entry-point=action_form
# Verify this entry point from the Python source
```
### C. action_execute Function
This function handles the actual data transfer to SFTP.

```bash
# Navigate to the directory containing the action_execute function code
# cd path/to/looker_sftp_action/action_execute_function_directory
# make surethe name of secret in Secret Manager matches sftp

gcloud functions deploy actionexecute \
 --region=$REGION \
 --project=$PROJECT_ID \
 --trigger-http \
 --entry-point=action_execute \
 --allow-unauthenticated \
 --runtime=python311 \
 --set-env-vars=REGION=$REGION \
 --set-env-vars=PROJECT_ID=$PROJECT_ID \
 --set-env-vars=LOOKER_ACTION_HUB_SECRET=$LOOKER_ACTION_HUB_SECRET \
 --set-env-vars=PROJECT_NUMBER=$PROJECT_NUMBER \
 --set-secrets=sftp_pem=sftp:1 

# Optional: For request verification from Looker
# --set-env-vars=LOOKER_ACTION_HUB_SECRET="your-strong-secret-for-verification"
```

### Grant the Cloud Function's service account permission to access the secret
1. Find the service account for your deployed function:
  It's usually YOUR_PROJECT_ID@appspot.gserviceaccount.com (for older runtimes)
    or service-YOUR_PROJECT_NUMBER@gcf-admin-robot.iam.gserviceaccount.com (for newer runtimes)
    Check in GCP IAM or the function's details page.
    Alternatively, use:
    gcloud functions describe YOUR_ACTION_EXECUTE_FUNCTION_NAME --region YOUR_REGION --format 'value(serviceAccountEmail)'
    Let's call this FUNCTION_SERVICE_ACCOUNT_EMAIL

# 2. Grant permission:

```bash
gcloud secrets add-iam-policy-binding YOUR_SECRET_NAME \
  --member="serviceAccount:FUNCTION_SERVICE_ACCOUNT_EMAIL" \
  --role="roles/secretmanager.secretAccessor" \
  --project=YOUR_PROJECT_ID
```

# 4. Add Action to Looker
In Looker, go to Admin > Platform > Actions.
Scroll to the bottom and click "Add Action Hub".
Action Hub URL: Enter the HTTPS Trigger URL of your action_list Cloud Function.
Authorization Token (Optional): If you set the LOOKER_ACTION_HUB_SECRET environment variable on your Cloud Functions, enter the same secret value here. This helps ensure that only Looker can call your action functions.
Click "Add Action Hub".
Your new SFTP action should now appear in the list of actions. If it's not enabled by default, enable it.

# Usage
Once the action is set up and enabled in Looker:
From a Look or a Dashboard, click the gear icon and choose "Send..." or "Schedule...".
In the "Where should this data go?" or "Destination" dropdown, select your new "SFTP (Ed25519/ECDSA)" action (the name will depend on what's defined in your action_list function).
The form fields defined in your action_form function will appear. Fill them out:
SFTP Hostname: e.g., sftp.example.com
SFTP Port: e.g., 22 (or your custom SFTP port)
SFTP Username: The username for the SFTP server.
SFTP Path: The full path on the server where the file should be saved (e.g., /uploads/looker/).
Filename: The desired filename (you can use Looker's filename templating).
Configure format, filters, and schedule settings as needed.
Click "Send" or "Save".
Looker will then trigger the action_execute Cloud Function, which will retrieve the key, connect to the SFTP server and transfer the file.

# Troubleshooting
Check Cloud Function Logs: If deliveries fail, the first place to check is the logs for your action_execute Cloud Function in Google Cloud Logging.

# Permissions:
Ensure the action_execute function's service account has the roles/secretmanager.secretAccessor permission for the specific secret.
Ensure your SFTP server's authorized_keys file for the target user contains the correct public key.
Key Format: Double-check that the private key stored in Secret Manager is in PEM format.
Firewall Rules: Ensure your SFTP server's firewall allows incoming connections from Google Cloud IP ranges (or more specifically, Cloud Functions egress IPs if you have configured a VPC connector with static NAT).
Ensure your SFTP server supports modern ciphers compatible.
Looker Action Hub Secret: If you set LOOKER_ACTION_HUB_SECRET, ensure it matches exactly in both the Cloud Function environment variable and the Looker Action Hub configuration.

# Contributing
Contributions are welcome! Please feel free to submit pull requests or open issues for bugs, feature requests, or improvements.
(Details on development setup, testing, and contribution guidelines can be added here if desired.)
License
(Specify the license for this code, e.g., MIT, Apache 2.0. If not specified in the original repository, you might state "License to be determined" or "See repository license file.")
