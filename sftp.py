import paramiko
import os
import json
import io

def get_cred_config():
    """Retrieve Cloud SQL credentials stored in Secret Manager
    or default to environment variables.

    Returns:
        A dictionary with Cloud SQL credential values
    """
    secret = os.environ.get("sftp_pem")
    if secret:
        print("got secret")
        return secret


def upload_file_sftp(
    sftp_host,
    sftp_port,
    sftp_user,
    local_file_path,
    remote_file_path,
    private_key_string=None,
    sftp_password=None
):

    print(f"sftp host: {sftp_host}")
    print(f"sftp port: {sftp_port}")
    print(f"sftp user: {sftp_user}")
    print(f"local_file_path: {local_file_path}")
    print(f"remote_file_path: {remote_file_path}")

    ssh_client = None
    sftp_client = None
    use_key_auth = bool(private_key_string)
    private_key_obj = None # Initialize here

    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        print(f"Connecting to {sftp_host}:{sftp_port} as {sftp_user}...")

        if use_key_auth:
            print("Attempting key-based authentication using provided key string.")
            if not isinstance(private_key_string, str):
                print("Error: private_key_string must be a string.")
                use_key_auth = False # Fallback if string not provided correctly
            else:
                try:
                    key_file_obj = io.StringIO(private_key_string)
                    
                    # Explicitly try loading as common key types
                    key_classes_to_try = [
                        paramiko.Ed25519Key,
                        paramiko.ECDSAKey
                        # paramiko.DSSKey, # DSS is older and sometimes problematic; add if needed
                    ]
                    
                    loaded_successfully = False
                    for key_cls in key_classes_to_try:
                        try:
                            key_file_obj.seek(0) # Reset stream for each parsing attempt
                            private_key_obj = key_cls.from_private_key(key_file_obj, password=None) # No password
                            print(f"Successfully loaded key as {key_cls.__name__} from string.")
                            loaded_successfully = True
                            break # Key loaded, exit loop
                        except paramiko.SSHException as e_ssh_type:
                            # This is expected if the key is not of the current type,
                            # or if it's encrypted (but we assume unencrypted).
                            print(f"DEBUG: Could not load key as {key_cls.__name__}: {e_ssh_type}")
                        except Exception as e_other_type:
                            # Catch any other unexpected error during a specific key type load
                            print(f"DEBUG: Unexpected error trying to load as {key_cls.__name__}: {e_other_type}")
                    
                    if not loaded_successfully:
                        print("Error: Failed to load private key from string using any known key type. "
                              "Ensure the key string is a valid unencrypted private key (OpenSSH or PEM format).")
                        use_key_auth = False # Fallback to password

                except Exception as e_load_key: # Catch errors like io.StringIO failing
                    print(f"Error preparing or loading SSH key from string: {e_load_key}")
                    use_key_auth = False # Fallback to password
            
            # Proceed with connection if key was loaded and use_key_auth is still true
            if use_key_auth and private_key_obj:
                 ssh_client.connect(
                    sftp_host,
                    port=sftp_port,
                    username=sftp_user,
                    pkey=private_key_obj,
                    allow_agent=False,
                    look_for_keys=False
                )
            else: # Key loading failed or wasn't attempted correctly, ensure use_key_auth is false
                use_key_auth = False


        if not use_key_auth: # True if key_string wasn't provided, or if key loading/auth failed
            if sftp_password:
                print("Attempting password-based authentication.")
                ssh_client.connect(
                    sftp_host,
                    port=sftp_port,
                    username=sftp_user,
                    password=sftp_password,
                    allow_agent=False,
                    look_for_keys=False
                )
            else:
                print("Key authentication not used or failed, and no sftp_password provided. Prompting for password...")
                pw_prompt = getpass.getpass(f"Enter password for {sftp_user}@{sftp_host}: ")
                ssh_client.connect(
                    sftp_host,
                    port=sftp_port,
                    username=sftp_user,
                    password=pw_prompt,
                    allow_agent=False,
                    look_for_keys=False
                )

        print("Connection established.")
        sftp_client = ssh_client.open_sftp()
        print("SFTP session opened.")

        print(f"Uploading '{local_file_path}' to '{remote_file_path}'...")
        sftp_client.put(local_file_path, remote_file_path)
        print("File uploaded successfully!")
        return True

    except paramiko.AuthenticationException:
        print("Authentication failed. Please check your credentials (key or password).")
    except paramiko.SSHException as ssh_ex: # Catches broader SSH issues including connection problems
        print(f"SSH error: {ssh_ex}")
    except FileNotFoundError:
        print(f"Error: Local file '{local_file_path}' not found during sftp.put().")
    except IOError as io_ex:
        print(f"IOError during SFTP operation (e.g., remote path issue): {io_ex}")
        print(f"Please ensure the remote directory '{os.path.dirname(remote_file_path)}' exists on the server.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if sftp_client:
            sftp_client.close()
            print("SFTP session closed.")
        if ssh_client:
            ssh_client.close()
            print("SSH connection closed.")
    return False
