import pickle
import os
import time

# ================================ Paths =============================
CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
INFO_FILE_PATH = os.path.join(CURRENT_DIR_PATH, "config.ini")
TOKEN_STORAGE_FILE = os.path.join(CURRENT_DIR_PATH, "token.pkl")
# ====================================================================


def save_token(token):
    # Create a dictionary to store the token and the timestamp
    data = {"token": token, "timestamp": time.time()}  # Store the current timestamp

    # Save the data to a pickle file
    with open(TOKEN_STORAGE_FILE, "wb") as file:
        pickle.dump(data, file)


def read_token():
    # Check if the pickle file exists
    if os.path.exists(TOKEN_STORAGE_FILE):
        with open(TOKEN_STORAGE_FILE, "rb") as file:
            data = pickle.load(file)

        # Get the timestamp and current time
        timestamp = data["timestamp"]
        current_time = time.time()

        # Check if the token was saved less than 23 hours ago
        if current_time - timestamp < 23 * 3600:  # 23 hours in seconds
            return data["token"]

    # If the file doesn't exist or the token is too old, return False
    return False



if __name__ == "__main__":
    print("This is a Module")
