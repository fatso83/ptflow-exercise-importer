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
import os
import sys
import argparse

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

parser = argparse.ArgumentParser()
parser.add_argument(
        "--image-dir", type=str, required=True,
        help="A directory containing image files that are named using a specific naming scheme: {id}-.*.png")
parser.add_argument(
        "--sheets-id", type=str, 
        help="The id of the Google Sheet containing exercise data (i.e. '18_LuqnjAmVzAL6zQzJKjSWqGgPMLgYx0I_k3wV2I2xg'")
parser.add_argument(
        "--bookkeeping-id", type=str, 
        help="A worksheet with this name will be created in the spreadsheet to keep tabs on what data has been uploaded")
parser.add_argument(
        "--session", type=str, 
        help="A valid session token taken from a browser to use when " 
        + "performing REST calls to the PTFLOW server. "
        + "Can also be set using the environment variable PTFLOW_SESSION.")
parser.add_argument(
        "--server", type=str, 
        help="The server url, including an optional port number (i.e. https://myserver.dev:443). "
        + "Can also be set using the environment variable PTFLOW_SERVER.")

# The ID and range of a sample spreadsheet.
SPREADSHEET_ID = "18_LuqnjAmVzAL6zQzJKjSWqGgPMLgYx0I_k3wV2I2xg"
RANGE_NAME = "Øvelser pri 1!A5:J"

def main():

    parsed = parser.parse_args()
    try:
        session = parsed.session or os.environ["PTFLOW_SESSION"]
        server = parsed.server or os.environ["PTFLOW_SERVER"]
    except KeyError as e:
        print("Server and session are required")
        sys.exit(1)

    image_dir = parsed.image_dir
    sheets_id = parsed.sheets_id or SPREADSHEET_ID

    print("session: %s\nserver: %s"%(session,server)) 

    values = get_spreadsheet_values(sheets_id, RANGE_NAME)
    # A stub for debugging
    # values = [["0003","foo","something"]]

    if not values:
        logger.error("No data found in spreadsheet.")
        sys.exit(1)
    
    logger.info("Got %s results from Google Sheets", len(values))

    for row in values:
        exercise = Exercise(row)

        images = get_images(image_dir, exercise.id)
        exercise.images.extend(images)

        createExercise(exercise, server, session, parsed.bookkeeping_id)


def createExercise(exercise,server, session, bookkeeping_id):

    # check if already uploaded - return early if so

    # upload images, get ids

    # upload exercise with image ids

    # log data to bookkeeping

def get_images(image_dir, exercise_id):
    # All these image paths assume the image dir is the subdir ./PACK
    glob_string = image_dir + exercise_id + "*.png"
    single_file_glob_string = image_dir + "SINGLE-STEP/" + exercise_id + "*SINGLE-STEP.png"
    image_list = glob.glob(glob_string)
    single_file = glob.glob(single_file_glob_string)

    assert not (len(single_file) > 0 and len(image_list) > 0)

    if image_list:
        image_list.sort()
        return image_list
    elif single_file:
        logger.debug("id=%s. Single image: %s" % (exercise_id, single_file[0]))
        return single_file
    else:
        raise Exception("No image found for id " + exercise_id) 
  

def get_spreadsheet_values(sheets_id, spreadsheet_range):
    # If modifying these scopes, delete the file token.pickle.
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

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
    result = sheet.values().get(spreadsheetId=sheets_id,
                                range=spreadsheet_range).execute()

    return result.get("values", [])

class Exercise:
    def __init__(self, row):
        required_length = 9+1
        list_length = len(row)
        missing_vals = required_length-list_length

        if missing_vals > 0: 
            row.extend(['']*missing_vals)
            self.extended = True
        else:
            self.extended = False

        self.id = row[0]
        self.priority = row[1]
        self.name = row[2]
        self.description1 = row[3]
        self.description2 = row[4]
        self.category = row[5]
        self.equipment = row[6]
        self.bodypart = row[7]
        self.target = row[8]
        self.synergist = row[9]

        self.images = []

    def __str__(self):
        args = (self.id, self.name, self.equipment, self.bodypart, self.target)
        return "Exercise{id=%s, name=%s, equipment=%s, bodypart=%s, target=%s}"%args

if __name__ == "__main__":
    main()
