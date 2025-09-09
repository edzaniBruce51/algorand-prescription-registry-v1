from flask import Flask, render_template, request, redirect, flash, jsonify, url_for
import json   # For encoding and decoding JSON data.
import os     # Access environment variables
import requests    # To send HTTP requests to the BaaS API
from dotenv import load_dotenv   #Loads .env file for secret configuration
from datetime import datetime, timezone     # Used for timestamps in UTC.

load_dotenv()

app = Flask(__name__)  #Initializes Flask app.
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'fallback-secret-for-dev-only')   # Loads secret key for session management and flash messages.

# BaaS API Configuration
BLOCKAPI_BASE_URL = os.getenv("BLOCKAPI_BASE_URL", "https://blockapi.co.za/api/v1")
BLOCKAPI_API_KEY = os.getenv("BLOCKAPI_API_KEY")    # API key for authentication
WEBHOOK_URL = os.getenv("WEBHOOK_URL")      # Where the BaaS platform will POST blockchain notifications.

# Simple in-memory storage for registered prescriptions (in production, use a database)
# This is a Python list in memory. While the Flask app is running, the presciptions list exists in RAM.
# Every element is a dictionary containing song info. 
# If your app restarts or redeploys, the list is cleared.
prescriptions = []

@app.route("/")
def index():
    sorted_prescriptions = sorted(prescriptions, key=lambda x: x.get("data_id", ""), reverse=True)
    return render_template("index.html", prescriptions=sorted_prescriptions)
 # passes the current prescription list to display all registered songs.


@app.route("/register_prescription", methods=["POST"])
def register_prescription():
    # Get form data
    try:
        patient_full_name = request.form.get("patient_full_name")
        patient_dob = request.form.get("patient_dob")          # YYYY-MM-DD
        prescription_date = request.form.get("prescription_date")
        medication_name = request.form.get("medication_name")
        dosage_strength = request.form.get("dosage_strength")
        route_of_administration = request.form.get("route_of_administration")
        frequency_duration = request.form.get("frequency_duration")
        quantity_to_dispense = request.form.get("quantity_to_dispense")
        refill_info = request.form.get("refill_info")
        prescriber_signature = request.form.get("prescriber_signature")


         # basic validation: required fields
        if not patient_full_name or not patient_dob or not medication_name:
            flash("Please fill required fields", "error")
            return redirect("/")


        # Generate unique identifiers for tracking / Generate unique IDs
        import time
        prescription_id = len(prescriptions) + 1  # Local tracking
        data_id = f"prescription_{int(time.time())}"  # Use timestamp for unique ID

        # Prepare song data for blockchain
        prescription_data = {
            "application": "prescriptionRegistry",
            "version": 1,
            "patient_full_name": patient_full_name,
            "patient_dob": patient_dob,
            "prescription_date": prescription_date,
            "medication_name": medication_name,
            "dosage_strength": dosage_strength,
            "route_of_administration": route_of_administration,
            "frequency_duration": frequency_duration,
            "quantity_to_dispense": quantity_to_dispense,
            "refill_info": refill_info,
            "prescriber_signature": prescriber_signature
        }

        # Prepare BaaS API payload according to their specification
        payload = {
            "dataSchemaName": "prescriptionRegistry",  # Table/schema name from sender perspective
            "dataId": data_id,                 # Row ID from sender perspective
            "jsonPayload": prescription_data           # The actual data to be hashed and stored
        }

        # Try different header formats - blockapi.co.za might use different auth
        headers = {
            "X-API-Key": BLOCKAPI_API_KEY,  # Common API key format
            "Content-Type": "application/json"
        }

        # Send request to correct BaaS API endpoint
        response = requests.post(
            f"{BLOCKAPI_BASE_URL}/blockchainTask",
            json=payload,
            headers=headers,
            timeout=30
        )

        # Handle response
        if response.status_code in [200, 201]:  # Accept both 200 and 201 as success
            # Parse the response to get BaaS task ID
            response_data = response.json()
            baas_task_id = response_data.get('data', {}).get('id')

            # Add to local storage for display with tracking info
            prescription_data['id'] = prescription_id
            prescription_data['data_id'] = data_id
            prescription_data['baas_task_id'] = baas_task_id
            prescription_data['status'] = 'pending' 
            prescriptions.append(prescription_data)    # Saves prescription locally with a pending status until the blockchain confirms
            flash(f"Prescription registered successfully! Tracking ID: {data_id}", "success")
            flash(f"BaaS Task ID: {baas_task_id} - Your prescription will be written to the blockchain shortly.", "info")
        else:
            flash(f"Error: {response.status_code} - {response.text}", "error")

    except Exception as e:
        flash(f"Error registering prescription: {e}", "error")

    return redirect("/")

# Receive blockchain updates
# whenever someone sends a POST request to /webhook/blockchain-notification, run the function below
# This function listens for blockchain updates → finds the correct prescription → updates its status and blockchain info → and confirms back to the webhook sender.
# Receive blockchain updates
@app.route("/webhook/prescription-notification", methods=["POST"])
def prescription_webhook():
    try:
        webhook_data = request.get_json(silent=True)
        if not webhook_data:
            print("Webhook error: no JSON body")
            return jsonify({"error": "Invalid webhook"}), 400

        print(f"Received webhook: {webhook_data}")

        data_id = webhook_data.get("dataId")
        results = webhook_data.get("BlockchainResults", [])

        tx_id = None
        explorer_url = None
        success_flag = None

        if results and isinstance(results, list):
            first = results[0]
            tx_id = first.get("transactionId")
            explorer_url = first.get("transactionExplorerUrl")
            success_flag = first.get("isSuccess")

        # Update prescriptions
        for prescription in prescriptions:
            if prescription.get("data_id") == data_id:
                if success_flag is True:
                    prescription["status"] = "confirmed"
                elif success_flag is False:
                    prescription["status"] = "failed"
                else:
                    prescription.setdefault("status", "pending")

                if tx_id:
                    prescription["blockchain_tx_id"] = tx_id
                if explorer_url:
                    prescription["explorer_url"] = explorer_url

                # Add webhook-provided payload & hash
                if "jsonPayloadHash" in webhook_data:
                    prescription["jsonPayloadHash"] = webhook_data["jsonPayloadHash"]
                if "jsonPayload" in webhook_data:
                    prescription["jsonPayload"] = webhook_data["jsonPayload"]

                print(f"Updated prescription {data_id}: {prescription}")
                break

        return jsonify({"message": "Webhook processed successfully"}), 200

    except Exception as e:
        print(f"Webhook exception: {e}")
        return jsonify({"error": str(e)}), 500


# JSON endpoint for frontend polling
@app.route("/prescriptions_json")
def prescriptions_json():
    return jsonify(prescriptions)


# verify transactions on the blockchain
# Updated verify_prescription route for app.py
# Updated verify_prescription route for app.py
@app.route("/verify_prescription", methods=["GET", "POST"])
def verify_prescription():
    if request.method == "POST":
        transaction_id = request.form.get("transactionId")
        verification_type = request.form.get("verification_type")  # Get the verification method
        json_payload_str = request.form.get("jsonPayload")
        json_payload_hash = request.form.get("jsonPayloadHash")
        
        verification_message = None
        verification_status = None
        
        if not transaction_id:
            flash("Transaction ID is required", "error")
            return redirect(url_for("verify_prescription"))
        
        if not verification_type:
            flash("Please select a verification method", "error")
            return redirect(url_for("verify_prescription"))
        
        try:
            headers = {
                "X-API-Key": BLOCKAPI_API_KEY,
                "Content-Type": "application/json"
            }
            verification_payload = {"transactionId": transaction_id}

            # Handle payload verification
            if verification_type == "payload":
                if not json_payload_str or not json_payload_str.strip():
                    verification_message = "JSON payload is required for payload verification"
                    verification_status = "error"
                    return render_template(
                        "verify_prescription.html",
                        tx_id=transaction_id,
                        verification_type=verification_type,
                        verification_message=verification_message,
                        verification_status=verification_status,
                        mode="post"
                    )
                
                try:
                    json_payload_obj = json.loads(json_payload_str)
                    verification_payload["jsonPayload"] = json_payload_obj
                except json.JSONDecodeError as e:
                    verification_message = f"Invalid JSON payload: {e}"
                    verification_status = "error"
                    return render_template(
                        "verify_prescription.html",
                        tx_id=transaction_id,
                        verification_type=verification_type,
                        verification_message=verification_message,
                        verification_status=verification_status,
                        mode="post"
                    )

            # Handle hash verification
            elif verification_type == "hash":
                if not json_payload_hash or not json_payload_hash.strip():
                    verification_message = "JSON payload hash is required for hash verification"
                    verification_status = "error"
                    return render_template(
                        "verify_prescription.html",
                        tx_id=transaction_id,
                        verification_type=verification_type,
                        verification_message=verification_message,
                        verification_status=verification_status,
                        mode="post"
                    )
                
                verification_payload["jsonPayloadHash"] = json_payload_hash

            # Make API call
            response = requests.post(
                f"{BLOCKAPI_BASE_URL}/blockchainTransaction/verify",
                json=verification_payload,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                try:
                    result = response.json()
                    
                    # Determine verification result for banner
                    # Check the actual fields returned by the API
                    is_hash_verified = result.get("data", {}).get("isJsonPayloadHashVerified", False)
                    is_tx_on_blockchain = result.get("data", {}).get("isTransactionIdOnBlockchain", False)
                    
                    # Also check direct fields in case API structure is different
                    if not is_hash_verified:
                        is_hash_verified = result.get("isJsonPayloadHashVerified", False)
                    if not is_tx_on_blockchain:
                        is_tx_on_blockchain = result.get("isTransactionIdOnBlockchain", False)
                    
                    if verification_type == "hash" and is_hash_verified and is_tx_on_blockchain:
                        verification_message = "✅ Hash verification successful! The data fingerprint matches the blockchain record."
                        verification_status = "success"
                    elif verification_type == "payload" and is_tx_on_blockchain:
                        # For payload verification, check if payload verification passed
                        is_payload_verified = result.get("data", {}).get("isJsonPayloadVerified", 
                                            result.get("isJsonPayloadVerified", False))
                        if is_payload_verified or is_hash_verified:  # Either payload or hash verified
                            verification_message = "✅ Payload verification successful! The data matches the blockchain record."
                            verification_status = "success"
                        else:
                            verification_message = "❌ Payload verification failed. The data does not match the blockchain record."
                            verification_status = "error"
                    else:
                        verification_message = "❌ Verification failed. The data does not match the blockchain record."
                        verification_status = "error"
                    
                    return render_template(
                        "verify_prescription.html",
                        tx_id=transaction_id,
                        result=result,
                        verification_type=verification_type,
                        verification_message=verification_message,
                        verification_status=verification_status,
                        mode="post"
                    )
                    
                except json.JSONDecodeError:
                    verification_message = "Received invalid response from blockchain API"
                    verification_status = "error"
                    return render_template(
                        "verify_prescription.html",
                        tx_id=transaction_id,
                        result={"raw_response": response.text},
                        verification_type=verification_type,
                        verification_message=verification_message,
                        verification_status=verification_status,
                        mode="post"
                    )
            else:
                verification_message = f"Verification failed: {response.text}"
                verification_status = "error"
                return render_template(
                    "verify_prescription.html",
                    tx_id=transaction_id,
                    verification_type=verification_type,
                    verification_message=verification_message,
                    verification_status=verification_status,
                    mode="post"
                )

        except Exception as e:
            verification_message = f"Error during verification: {str(e)}"
            verification_status = "error"
            return render_template(
                "verify_prescription.html",
                tx_id=transaction_id,
                verification_type=verification_type,
                verification_message=verification_message,
                verification_status=verification_status,
                mode="post"
            )

    # GET request - show the form
    tx_id = request.args.get("tx_id", "")
    verification_type = request.args.get("verification_type", "payload")  # Default to payload
    return render_template(
        "verify_prescription.html", 
        tx_id=tx_id, 
        verification_type=verification_type,
        mode="get"
    )


# Application Runner.
# Starts Flask server on Render or local machine.
# Uses environment variable PORT if provided.
if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))