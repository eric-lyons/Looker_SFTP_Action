from auth import authenticate
import base64
from flask import Response
from icon import icon_data_uri
import io, zipfile, json
import os
import pandas as pd
from pandas import ExcelWriter
from sftp import upload_file_sftp, get_cred_config
import tempfile
import zlib


# https://github.com/looker-open-source/actions/blob/master/docs/action_api.md#action-form-endpoint
def action_form(request):
    """Return form endpoint data for action"""

    request_json = request.get_json()
    form_params = request_json['form_params']
    print(form_params)

    response = [
        {"name": "filename", "label": "filename", "type": "string", "required":True},
        {"name": "host", "label": "host", "type": "string", "required":True},
        {"name": "username", "label": "username", "type": "string", "required": True},
        {"name": "port", "label": "port", "type": "string" , "required": True}
      ]


    print('returning form json: {}'.format(json.dumps(response)))
    return Response(json.dumps(response), status=200, mimetype='application/json')


def action_list(request):
    """Return action hub list endpoint data for action"""
    project_number = os.environ.get("PROJECT_NUMBER")
    region = os.environ.get("REGION")

    form_url = f"https://actionform-{project_number}.{region}.run.app/action_form"
    print(f"form url: {form_url}")
    execute_url = f"https://actionexecute-{project_number}.{region}.run.app/action_execute"
    print(f"execute url: {execute_url}")
    response = {
        'label': 'Secure SFTP',
        'integrations': [{
            'name': 'SecureSFTP',
            'label': 'SecureSFTP',
            "icon_data_uri": icon_data_uri,
            'form_url': form_url,
            'url': execute_url,
            'supported_action_types': ['dashboard'],
            'supported_download_settings': ['url'],
            'supported_formats': ['csv_zip'],
            'supported_formattings': ['unformatted']
        }]
    }

    print('returning integrations json')
    return Response(json.dumps(response), status=200, mimetype='application/json')



tmpdir = tempfile.gettempdir()

def convertname(request_json):
    # Create a base temporary directory for this operation
    # This directory will NOT be automatically cleaned up by this function.
    try:
        operation_dir = tempfile.mkdtemp() 
    except OSError as e:
        print(f"Error creating temporary directory: {e}")
        raise RuntimeError(f"Failed to create temporary directory: {e}") from e
    
    print(f"Working in temporary directory: {operation_dir}")
    excel_file_path = None # Ensure it's defined for return in case of early exit (though we raise)

    try:
        # 1. Save and Extract Zip
        zip_file_path = os.path.join(operation_dir, "output.zip")
        
        try:
            attachment_data = request_json["attachment"]['data']
        except KeyError as e:
            print(f"Error: Missing 'attachment' or 'data' in request_json: {e}")
            raise ValueError(f"Request JSON missing expected attachment data structure: {e}") from e
        except TypeError as e: # Handle cases where request_json or "attachment" is not a dictionary
            print(f"Error: Invalid request_json structure for attachment: {e}")
            raise ValueError(f"Request JSON has invalid structure for attachment: {e}") from e

        try:
            decoded_zip_data = base64.b64decode(attachment_data)
        except base64.binascii.Error as e: # base64.Error is an alias for binascii.Error
            print(f"Error decoding base64 attachment data: {e}")
            raise ValueError(f"Invalid base64 attachment data: {e}") from e

        try:
            with open(zip_file_path, 'wb') as result:
                result.write(decoded_zip_data)
        except IOError as e:
            print(f"Error writing decoded zip data to {zip_file_path}: {e}")
            raise RuntimeError(f"Failed to save zip file: {e}") from e
        
        print(f"output.zip created in {operation_dir}. Contents: {os.listdir(operation_dir)}")

        try:
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                zip_ref.extractall(operation_dir)
        except zipfile.BadZipFile as e:
            print(f"Error: Uploaded file is not a valid zip file or is corrupted: {e}")
            raise ValueError(f"Invalid or corrupted zip file: {e}") from e
        except FileNotFoundError: # Should not happen if previous step succeeded
            print(f"Error: Zip file {zip_file_path} not found for extraction.")
            raise
        except (IOError, OSError) as e:
            print(f"Error extracting zip file {zip_file_path}: {e}")
            raise RuntimeError(f"Zip extraction failed: {e}") from e
        
        print(f"Zip extracted. Contents of {operation_dir}: {os.listdir(operation_dir)}")

        # 2. Locate the folder containing CSVs
        csv_files_location = operation_dir
        try:
            dir_contents = os.listdir(operation_dir)
            potential_data_folders = [
                d for d in dir_contents
                if os.path.isdir(os.path.join(operation_dir, d))
            ]
        except OSError as e:
            print(f"Error listing directory contents of {operation_dir}: {e}")
            raise RuntimeError(f"Failed to access extracted files: {e}") from e

        if len(potential_data_folders) == 1:
            csv_files_location = os.path.join(operation_dir, potential_data_folders[0])
            print(f"Found single extracted subfolder for CSVs: {csv_files_location}")
        elif len(potential_data_folders) > 1:
            print(f"Warning: Multiple subfolders found: {potential_data_folders}. Assuming CSVs are in the first one: {potential_data_folders[0]} or directly in {operation_dir}.")
            first_potential_folder = os.path.join(operation_dir, potential_data_folders[0])
            try:
                if any(f.lower().endswith('.csv') for f in os.listdir(first_potential_folder)):
                    csv_files_location = first_potential_folder
                else:
                    print(f"No CSVs in {first_potential_folder}, will check root {operation_dir}")
            except OSError as e: # Error listing first_potential_folder
                 print(f"Error accessing subfolder {first_potential_folder}, will check root {operation_dir}. Error: {e}")

        else: # No subdirectories found
            print(f"No subfolders found after extraction. Assuming CSVs are in: {operation_dir}")
        
        try:
            csv_files = [f for f in os.listdir(csv_files_location) if f.lower().endswith('.csv')]
        except FileNotFoundError: # If csv_files_location somehow became invalid (e.g. symlink issue)
            print(f"Error: The determined CSV location '{csv_files_location}' does not exist.")
            raise
        except OSError as e:
            print(f"Error listing CSV files in {csv_files_location}: {e}")
            raise RuntimeError(f"Failed to list CSV files: {e}") from e
            
        if not csv_files and csv_files_location != operation_dir:
            print(f"No CSVs in {csv_files_location}, checking root {operation_dir} again.")
            csv_files_location = operation_dir
            try:
                csv_files = [f for f in os.listdir(csv_files_location) if f.lower().endswith('.csv')]
            except OSError as e:
                print(f"Error listing CSV files in root {operation_dir} after fallback: {e}")
                raise RuntimeError(f"Failed to list CSV files in fallback location: {e}") from e

        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {operation_dir} or its direct subdirectories after extraction.")
        
        print(f"Found CSV files: {csv_files} in {csv_files_location}")

        # 3. Create Excel file
        excel_file_path = os.path.join(operation_dir, 'tabbed.xlsx')
        excel_writer_instance = None # Initialize for finally block or specific error handling
        
        try:
            excel_writer_instance = pd.ExcelWriter(excel_file_path, engine='xlsxwriter')
        except Exception as e_writer_init: # Could be various pandas/xlsxwriter exceptions
            print(f"Error initializing ExcelWriter for {excel_file_path}: {e_writer_init}")
            raise RuntimeError(f"Failed to initialize Excel file creation: {e_writer_init}") from e_writer_init

        for f_name in csv_files:
            full_csv_path = os.path.join(csv_files_location, f_name)
            print(f"Processing CSV: {full_csv_path}")
            try:
                df = pd.read_csv(full_csv_path)
                if df.empty:
                    print(f"Warning: CSV file {full_csv_path} is empty. An empty sheet will be created.")
            except pd.errors.EmptyDataError:
                print(f"Warning: CSV file {full_csv_path} is empty (pd.errors.EmptyDataError). Creating an empty sheet.")
                df = pd.DataFrame() # Create an empty DataFrame to proceed robustly
            except pd.errors.ParserError as e_parse:
                print(f"Error parsing CSV file {full_csv_path}: {e_parse}")
                raise ValueError(f"Could not parse CSV file {full_csv_path}: {e_parse}") from e_parse
            except FileNotFoundError: # Should ideally not occur if listing was correct
                print(f"Error: CSV file {full_csv_path} not found during processing loop.")
                raise # Propagate as it indicates a prior logic flaw
            except Exception as e_read_csv: # Catch any other pandas read_csv error
                print(f"Error reading CSV file {full_csv_path} with pandas: {e_read_csv}")
                raise RuntimeError(f"Failed to read CSV {full_csv_path}: {e_read_csv}") from e_read_csv
            
            sheet_name = os.path.splitext(f_name)[0]
            sheet_name = "".join(c for c in sheet_name if c.isalnum() or c in (' ', '_', '-'))[:31]
            if not sheet_name: # Handle case where sanitization results in an empty string
                sheet_name = f"Sheet_{csv_files.index(f_name) + 1}" # Generic name
                print(f"Warning: Sanitized sheet name for {f_name} was empty. Using generic name: {sheet_name}")

            try:
                df.to_excel(excel_writer_instance, sheet_name=sheet_name, index=False)
            except Exception as e_to_excel: 
                print(f"Error writing sheet '{sheet_name}' (from CSV '{f_name}') to Excel: {e_to_excel}")
                raise RuntimeError(f"Failed to write sheet '{sheet_name}' from CSV '{f_name}': {e_to_excel}") from e_to_excel
        
        try:
            if excel_writer_instance:
                 excel_writer_instance.close() # This saves the file with xlsxwriter engine
                 print(f"Excel file successfully created and saved at: {excel_file_path}")
            else:
                # This state should not be reached if ExcelWriter init failure raises properly.
                print("Critical Error: Excel writer was not initialized, cannot save Excel file.")
                raise RuntimeError("Excel writer instance is missing prior to closing.")
        except Exception as e_close: # Catches errors during writer.close()
            print(f"Error saving/closing Excel file {excel_file_path}: {e_close}. File may be corrupt or incomplete.")
            raise RuntimeError(f"Failed to save/finalize Excel file {excel_file_path}: {e_close}") from e_close
        
        print(f"Contents of {operation_dir} before return: {os.listdir(operation_dir)}")
        # The following print statements were part of the original, kept as placeholders/debug.
        print("Uploading dashboard...") # Placeholder for your actual upload logic
        print("Upload complete!")

        return excel_file_path

    except Exception as e_outer:
        # This is the main catch block for convertname.
        # It catches any exception not handled by inner blocks or re-raised by them.
        print(f"An error occurred in convertname function: {e_outer}")
        # Add more details if possible, e.g., type of exception
        print(f"Error type: {type(e_outer).__name__}")
        # Cleanup of operation_dir is stated to be caller's responsibility.
        # Re-raise the exception so action_execute can handle it and return a proper error response.
        raise

def parse_port_string(port_str):
    """
    Tries to convert a string variable 'port_str' to an integer.
    Returns the integer if successful.
    Returns an error message string if it cannot be converted.
    The general default port for the system (e.g., SSH) is 22,
    which the caller can use if this function returns an error.
    """
    if port_str is None: # Explicit check for None
        return "Error: Port input is None. Port type must be an integer."
    try:
        port_int = int(port_str)
        # Optional: You might want to add port range validation here (e.g., 1-65535)
        if not (0 < port_int <= 65535): # Common port range
            return f"Error: Port number {port_int} is out of valid range (1-65535)."
        return port_int
    except ValueError:
        return f"Error: Port '{port_str}' is not a valid integer."
    except TypeError: # Should be caught by (port_str is None) or int() if not string-like
        return f"Error: Port input type is invalid ({type(port_str)}). Port must be a string representing an integer."


# https://github.com/looker-open-source/actions/blob/master/docs/action_api.md#action-execute-endpoint
def action_execute(request):
    auth = authenticate(request)
    if auth.status_code != 200:
        return auth
        
    try:
        try:
            request_json = request.get_json()
            if request_json is None:
                print("Error: Failed to parse request JSON or request body is empty.")
                # Using json.dumps for error response consistency
                return Response(json.dumps({"error": "Invalid JSON payload. Request body might be empty or not JSON.", "status": "failure"}), status=400, mimetype='application/json')
        except Exception as e_json_parse: # Catches Werkzeug BadRequest or other parsing errors
            print(f"Error parsing request JSON: {e_json_parse}")
            return Response(json.dumps({"error": f"Malformed JSON request: {str(e_json_parse)}", "status": "failure"}), status=400, mimetype='application/json')

        print("Preparing for SFTP operation and file processing...") # Clarified original print

        try:
            key = get_cred_config()
        except Exception as e_cred:
            print(f"Error getting credentials from get_cred_config: {e_cred}")
            # It's good practice to not expose raw credential errors if they are sensitive.
            return Response(json.dumps({"error": "Credential configuration error. Check server logs.", "status": "failure"}), status=500, mimetype='application/json')

        try:
            # Safely access form_params and its keys
            form_params = request_json.get("form_params")
            if form_params is None:
                raise KeyError("form_params missing from request JSON")
            
            host = form_params["host"]
            username = form_params["username"]
            filename = form_params["filename"]
            port_str = form_params.get("port") # Use .get for port_str to handle if it's missing, then parse_port_string handles None

        except KeyError as e_key:
            param_name = str(e_key).strip("'")
            print(f"Error: Missing required form parameter: {param_name}")
            return Response(json.dumps({"error": f"Missing form_params: '{param_name}' is required.", "status": "failure"}), status=400, mimetype='application/json')
        except TypeError as e_type: # If request_json or form_params is not a dict as expected
            print(f"Error: form_params is not structured correctly or request_json is invalid: {e_type}")
            return Response(json.dumps({"error": f"Invalid form_params structure: {str(e_type)}", "status": "failure"}), status=400, mimetype='application/json')

        port_or_error = parse_port_string(port_str)
        if isinstance(port_or_error, str) and port_or_error.startswith("Error:"):
            print(f"Invalid port configuration: {port_or_error}")
            return Response(json.dumps({"error": f"Invalid port: {port_or_error}", "status": "failure"}), status=400, mimetype='application/json')
        port = port_or_error # Now, port is a validated integer

        print(f"SFTP parameters: Host={host}, Username={username}, Port={port}, TargetFilename={filename}")
        print("Starting file conversion process...")
        
        path_to_excel = None # Initialize
        try:
            path_to_excel = convertname(request_json)
            # convertname now raises exceptions on failure, so path_to_excel should be valid if no exception.
            if not path_to_excel or not os.path.exists(path_to_excel):
                 # This case should ideally be covered by exceptions from convertname
                 print(f"Error: convertname completed but returned an invalid path ('{path_to_excel}') or file does not exist.")
                 raise FileNotFoundError("Excel file creation process completed, but the output file is missing or path is invalid.")
        except Exception as e_convert: 
            print(f"Error during file conversion (convertname): {e_convert}")
            # Consider logging traceback for server-side debugging:
            # import traceback; traceback.print_exc()
            return Response(json.dumps({"error": f"File conversion process failed: {str(e_convert)}", "status": "failure"}), status=500, mimetype='application/json')

        print(f"File conversion successful. Excel file at: {path_to_excel}")
        print(f"Attempting to upload {path_to_excel} to SFTP server...")
        try:
            upload_file_sftp(
                host,
                port,
                username,
                path_to_excel,
                filename,
                key
            )
            print("SFTP upload successful.")
        except Exception as e_sftp: 
            print(f"Error during SFTP upload: {e_sftp}")
            # import traceback; traceback.print_exc()
            # Be cautious about exposing raw SFTP error details to client
            return Response(json.dumps({"error": f"SFTP upload failed. Check server logs for details. Error: {str(e_sftp)}", "status": "failure"}), status=500, mimetype='application/json')
        
        # Original debug prints for action_params and form_params
        try:
            # Attachment data was already used in convertname, no need to re-access unless for other purposes
            # attachment_info = request_json.get('attachment', {}) # Safely get attachment
            # print(f"Attachment info (summary): { {k: type(v) for k,v in attachment_info.items()} }")


            action_params_data = request_json.get('data') # 'data' field might be optional
            if action_params_data is not None:
                print(f"Action params (request_json['data']): {action_params_data}")
            else:
                print("No 'data' field in request_json (this may be normal).")
            
            # form_params already extracted, printing for consistency with original debug log
            # Re-accessing form_params to show what was received.
            form_params_debug = request_json.get('form_params', {})
            print(f"Form params (request_json['form_params']) for debug: {form_params_debug}")

        except Exception as e_debug_print:
            # These are for debugging, so failure here is not critical to the action's success
            print(f"Warning: Minor error accessing optional data for debug printing: {e_debug_print}")

        print("Action execute handler completed successfully.")
        return Response(json.dumps({"status": "success", "message": "File processed and uploaded successfully."}), status=200, mimetype='application/json')

    except Exception as e_global_handler: # Broad catch-all for any unhandled errors in action_execute
        print(f"Unhandled critical error in action_execute: {e_global_handler}")
        # import traceback
        # traceback.print_exc() # For detailed server-side debugging
        
        # Generic error for the client
        error_message = f"An unexpected server error occurred. Please contact support. Ref: {type(e_global_handler).__name__}"
        return Response(json.dumps({"error": error_message, "status": "failure"}), status=500, mimetype='application/json')
