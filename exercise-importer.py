# coding=utf-8

# Script to do batch uploading of exercises

# DEFINITIONS 
# unfinished exercise: only data uploaded (no image ids). no trace in sheet, only in DB
#
# MAIN ALGO
# support resuming session by filtering out already processed ids and continuing
# does not support unfinished data uploads (meaning aborting program while uploading images or json)
#
# get exercise data from google sheet
# get previous result data, if any, to continue a previous session
#
# for each unprocessed exercise:
    # get matching image file for that exercise
    # handle exercise depending on number of images present
    #   - if more than two images, skip exercise creation
    #   - upload images
    #   - upload data with guids of uploaded images
    #   - store result data in spreadsheet (separate tab using session id)
    #       - datetime
    #       - guid of image1 and image2
    #       - guid of exercise
# print stats

from __future__ import print_function
import pickle
import glob
import logging
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# logging.basicConfig(filename="example.log", filemode="w", level=logging.DEBUG)
# logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("ptflow")
try:
    logger.setLevel(os.environ["PTFLOW_IMPORTER_LOG_LEVEL"].upper())
except Exception as e:
    logger.info("Using default log level")
    logger.setLevel(logging.INFO)

ch = logging.StreamHandler()
logger.addHandler(ch)


# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# The ID and range of a sample spreadsheet.
SPREADSHEET_ID = "18_LuqnjAmVzAL6zQzJKjSWqGgPMLgYx0I_k3wV2I2xg"
RANGE_NAME = "Øvelser pri 1!A5:J"
IMAGE_DIRECTORY="/Users/carlerik/ptflow-exercises/PACK/"

def main():
    """Shows basic usage of the Sheets API.
    Prints values from a sample spreadsheet.
    """
    creds = None
    # The file token.pickle stores the user"s access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    service = build("sheets", "v4", credentials=creds)

    # Call the Sheets API
    logger.debug("Calling sheets API")
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                range=RANGE_NAME).execute()
    values = result.get("values", [])
    # A stub for debugging
    # values = [("0003","foo","something")]
    
    logger.info("Got %s results from Google Sheets", len(values))

    if not values:
        logger.error("No data found.")
    else:
        for row in values:
            id = row[0]
            glob_string = IMAGE_DIRECTORY + id + "*.png"
            single_file_glob_string = IMAGE_DIRECTORY + "SINGLE-STEP/" + id + "*SINGLE-STEP.png"
            image_list = glob.glob(glob_string)
            single_file = glob.glob(single_file_glob_string)

            assert not (len(single_file) > 0 and len(image_list) > 0)
            if image_list:
                image_list.sort()
                image1 = image_list[0]

                logger.debug("%s, %s. Multiple images. Showing first: %s" % (row[0], row[2], image1))
                if len(image_list) > 2:
                    logger.warning("More than two images for id \"%s\". Skipping exercise creation", id)
                    continue
            elif single_file:
                logger.debug("%s, %s. Single image: %s" % (row[0], row[2], single_file[0]))
            else:
                raise Exception("No image found for id " + id) 

# def createExercises():
    # todo

if __name__ == "__main__":
    main()
