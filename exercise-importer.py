#!/usr/bin/env python3
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
    #   - store result data  somewhere using the session key   
    #       - id
    #       - datetime
    #       - guid of exercise
    #       - guid of image1 and image2? optional
# print stats

from __future__ import print_function
import requests
import datetime
# import dateutil.parser  as parser
import uuid
import time
import pickle
import glob
import logging
import os
import sys
import argparse
import yaml

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


# The ID and range of a sample spreadsheet.
SPREADSHEET_ID = "18_LuqnjAmVzAL6zQzJKjSWqGgPMLgYx0I_k3wV2I2xg"
RANGE_NAME = "Import pri 1 og 2!A2:Q"

# For development using mock data
use_fakes = False

logging.basicConfig(
        filename="importer.log", filemode="a", 
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger("ptflow")

formatter = logging.Formatter('[%(asctime)s]    %(message)s')
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)
try:
    ch.setLevel(os.environ["PTFLOW_IMPORTER_LOG_LEVEL"].upper())
except Exception as exception:
    ch.setLevel(logging.INFO)

argparser = argparse.ArgumentParser()
argparser.add_argument(
        "--image-dir", type=str, required=True,
        help="A directory containing image files that are named using a specific naming scheme: {id}-.*.png")
argparser.add_argument(
        "--sheets-id", type=str, 
        help="The id of the Google Sheet containing exercise data (i.e. '18_LuqnjAmVzAL6zQzJKjSWqGgPMLgYx0I_k3wV2I2xg'")
argparser.add_argument(
        "--bookkeeping-id", type=str, required=True,
        help="A worksheet with this name will be created in the spreadsheet to keep tabs on what data has been uploaded")
argparser.add_argument(
        "--session-token", type=str, 
        help="A valid session token taken from a browser to use when " 
        + "performing REST calls to the PTFLOW server. "
        + "Can also be set using the environment variable PTFLOW_TOKEN.")
argparser.add_argument(
        "--server", type=str, 
        help="The server url, including an optional port number (i.e. https://myserver.dev:443). "
        + "Can also be set using the environment variable PTFLOW_SERVER.")

def main():
    parsed = argparser.parse_args()
    try:
        session_token = parsed.session_token or os.environ["PTFLOW_TOKEN"]
        server = parsed.server or os.environ["PTFLOW_SERVER"]

        logger.debug("Server URL: %s"%server)
        logger.debug("Session token: %s"%session_token) 
    except KeyError as e:
        print("Server and session token are required")
        sys.exit(1)

    if use_fakes:
        logger.info("Using fakes for data")
        uploader = FakeUploader() # quick testing
        get_exercise_rows = get_stubbed_rows
    else:
        uploader = RealUploader(server, session_token)
        get_exercise_rows = get_spreadsheet_values

    image_dir = parsed.image_dir
    sheets_id = parsed.sheets_id or SPREADSHEET_ID

    values = get_exercise_rows(sheets_id, RANGE_NAME)

    if not values:
        logger.error("No data found in spreadsheet.")
        sys.exit(1)
    
    logger.info("Got %s exercise rows from Google Sheets", len(values))

    # init bookkeeping file
    if not os.path.isdir("bookkeeping"):
        os.mkdir("bookkeeping")
    oplog_filename = "bookkeeping/%s-log.yml"%parsed.bookkeeping_id

    uploads = create_upload_map(oplog_filename)
    if len(uploads.keys()):
        logger.info("Continuing uploads from previous session ...")

    logger.debug("Starting to loop through values from spreadsheet")
    for row in values:
        exercise = Exercise.from_row(row)
        logger.debug(str(exercise))

        try:
            images = get_images(image_dir, exercise.id)

            # check if already uploaded - return early if so
            if exercise.id in uploads and uploads[exercise.id].status == Status.OK:
                logger.info("Already uploaded exercise '%s' (server id: %s). Skipping.", exercise.id, uploads[exercise.id].uuid)
                continue

            result = upload_exercise(exercise, images, uploader)

        except NonConformingImagesException as exception:
            logger.warning(exception)
            result = LoggedExercise.from_failure(exercise.id, Status.SKIPPED, str(exception))

        logger.debug("Result of upload:"+str(result))
        add_result_to_oplog(result, oplog_filename)

    summary = create_summary(oplog_filename, values)
    difference_ids = summary[3]
    print("\nFinished uploading!")
    print(80*"-")
    print("Total number of exercises in Google Sheet: %d" % len(values))
    print("Total number of exercises processed: %d" % summary[0])
    if len(difference_ids) > 0:
        print("The ids that are missing from one or the other are " + str(difference_ids))
    print("Failed uploads: %d" % summary[1])
    print("Skipped uploads: %d" % summary[2])
    print("\nLogfile: importer.log")
    print(80*"-")


def create_upload_map(oplog_filename):
    uploads = dict()

    if not os.path.isfile(oplog_filename):
        return uploads

    with open(oplog_filename, "r") as file: 
        previous_session = yaml.safe_load(file)

    for item in previous_session:
        tmp = LoggedExercise(
                item['exercise_id'], 
                item['uuid'] if 'uuid' in item else '' , 
                item['status'], 
                item['cts'])
        uploads[tmp.exercise_id] = tmp

    return uploads

def add_result_to_oplog(item, log_filename):
    """Log the upload for bookkeeping

    Makes it possible to later continue
    from the last uploaded exercise by
    reading in the list of uploads.
    """

    with open(log_filename, "a+") as file: 
        file.write(item.to_yaml_list_item())

def upload_exercise(exercise, images, uploader):

    logger.debug("Uploading images for exercise %s", exercise.id)

    image_uuids = { 
            'start': uploader.upload_image(images[0]),
            'end': uploader.upload_image(images[1]) }
    logger.debug("Got image uuids: %s"%str(image_uuids))

    logger.info("Uploading exercise %s", exercise.id)
    uploader.upload_exercise(exercise)

    timestamp = datetime.datetime.utcnow()
    return LoggedExercise(exercise.id, '22238b0e-f3b9-11ea-9377-00155d1775a6', Status.OK, timestamp, images, image_uuids)

def uuid_string():
    return str(uuid.uuid4())

class RealUploader:

    def __init__(self, server, bearer_token):
        logger.debug("Initialized uploader with bearer token {0}".format(bearer_token))
        self.server = server
        self.bearer_token = bearer_token

    def __headers(self):
        return {
                'Authorization': 'Bearer ' + self.bearer_token,
                'Content-Type': 'application/json'
                }

    def upload_image(self, image):
        """See ApiImageController
         --> { image:'21fd2176-f3b9-11ea-ae83-00155d1775a6' }
        """
        return uuid_string()

    def upload_exercise(self, exercise):
        """See docs for ApiExerciseController.createAction"""
        r = requests.post(
                self.server + "/api/1/exercises", 
                json = exercise.__dict__,
                timeout = 1.0,
                headers = self.__headers() )
        logger.debug("Exercise response: {0}".format(r))
        r.raise_for_status()

        json_response = r.json()
        logger.debug("Exercise response json: {0}".format(json_response))

        return json_response.exercise.id

class FakeUploader:

    def upload_image(self, image):
        logger.debug("Fake image upload of " + image)
        time.sleep(1)
        return uuid_string()


    def upload_exercise(self, exercise):
        logger.debug("Fake exercise upload of " + exercise.id)
        time.sleep(2)
        return uuid_string()

def get_images(image_dir, exercise_id):
    # All these image paths assume the image dir is the subdir ./PACK
    glob_string = image_dir + exercise_id + "*.png"
    single_file_glob_string = image_dir + "SINGLE-STEP/" + exercise_id + "*SINGLE-STEP.png"
    image_list = glob.glob(glob_string)
    single_file = glob.glob(single_file_glob_string)

    assert not (len(single_file) > 0 and len(image_list) > 0)

    if image_list:
        image_list.sort()

        if len(image_list) > 2:
            raise TooManyImagesException("%s images found for %s. Require only two for start/end"%(len(image_list), exercise_id));

        return image_list
    elif single_file:
        logger.debug("id=%s. Single image: %s" % (exercise_id, single_file[0]))
        return single_file
    else:
        raise NoImagesException("No images found for id " + exercise_id) 

class NonConformingImagesException(Exception):
    pass

class NoImagesException(NonConformingImagesException):
    pass

class TooManyImagesException(NonConformingImagesException):
    pass

def get_stubbed_rows(ignore1,ignore2):
    return [
        # ["0000","","","", "name", "type", "subtype", "equipment", "Body Part", "focus_primary", "", "description", "", "", "", "", "tags"],
          ["0001","","","", "Air Bike", "Body Weight", "", "Body weight", "", "Waist", "", "Start flat on your back ...", "", "", "", "", "Obliques, Gluteus Maximus, Quadriceps, Rectus Abdominis"],
          ["0003","","","", "Air Bike3", "Body Weight", "", "Body weight", "", "Waist", "", "Start flat on your back ...", "", "", "", "", "Obliques, Gluteus Maximus, Quadriceps, Rectus Abdominis"],
          ["0004","","","", "Air Bike4", "Body Weight", "", "Body weight", "", "Waist", "", "Start flat on your back ...", "", "", "", "", "Obliques, Gluteus Maximus, Quadriceps, Rectus Abdominis"],
          ["0005","","","", "Air Bike5", "Body Weight", "", "Body weight", "", "Waist", "", "Start flat on your back ...", "", "", "", "", "Obliques, Gluteus Maximus, Quadriceps, Rectus Abdominis"]
        ]

def get_spreadsheet_values(sheets_id, spreadsheet_range):
    """Get the Google spreadsheet with the exercises

    This gets us a list of lists - each list representing a row
    """
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

    logger.warning("TODO:remove limit ")
    return result.get("values", [])[0:5]

def create_summary(oplog_filename, rows):
    upload_map = create_upload_map(oplog_filename)

    failed = 0
    skipped = 0
    for entry in upload_map.values():
        if entry.status == Status.SKIPPED: skipped += 1
        if entry.status == Status.FAILED : failed += 1

    spreadsheet_ids = [row[0] for row in rows]
    upload_ids = upload_map.keys()
    difference_ids = list( set(spreadsheet_ids).symmetric_difference(set(upload_ids)))
    logger.debug(spreadsheet_ids)
    logger.debug(upload_ids)
    logger.debug(difference_ids)

    return (len(upload_map.keys()), failed, skipped, difference_ids)

class LoggedExercise:

    @staticmethod
    def from_failure(id, status, reason):
        timestamp = datetime.datetime.utcnow()
        return LoggedExercise(id, None, status, timestamp, reason = reason)

    def __init__(self, exercise_id, uuid, status, timestamp, images = None, image_uuids = None, reason = None):
        self.uuid = uuid
        self.exercise_id = exercise_id
        self.status = status
        self.images = images
        self.image_uuids = image_uuids
        self.reason = reason # failure or skip reason

        self.cts = timestamp
        if type(timestamp) is not str:
            # serialize the timestamp to iso8601 to make it readable
            # across readers. otherwise would get python specific
            self.cts = timestamp.isoformat()

    def to_yaml_list_item(self):
        """Creates a YAML string representation of the instance"""

        # remove fields with the value None
        dictionary = {k:v for k,v in self.__dict__.items() if v}

        # wrap the dictionary in a list to produce a single item
        return yaml.dump([dictionary], default_flow_style=False)

    def __repr__(self):
        args = (self.exercise_id, self.uuid, self.status, self.cts)
        return "LoggedExercise(%s, %s, %s, %s)"%args

class Exercise:
    """Create an exercise representation from a row
    """

    TYPES = ["STRENGTH", "COORDINATION", "WEIGHT", "CARDIO", 
            "MOBILITY", "KETTLEBELLS", "SUSPENSIONTRAINING"]

    @staticmethod
    def from_row(row):
        """Basically a factory method: spreadsheet row to instance"""

        def convert_type(literal_type):
            typeMap = {
                    'Body Weight': 'WEIGHT',
                    'Flexibility Training': 'MOBILITY',
                    'Balance & Coordination': 'COORDINATION',
                    'Strength': 'STRENGTH',
                    'Sling suspension': 'SUSPENSIONTRAINING',
                    }
            if literal_type in typeMap:
                return typeMap[literal_type]
            else: 
                # fallback for unknown types
                # if it is wrong, it will fail in validate()
                return literal_type.upper()


        required_length = 17 # A2-Q2
        list_length = len(row)
        missing_vals = required_length-list_length

        if missing_vals > 0: 
            row.extend(['']*missing_vals)

        id = row[0]
        name = row[4]
        type = convert_type(row[5])
        subtype = row[6]
        focus_prim = row[9]
        focus_sec = row[10]
        description = row[11]
        notes = ''

        return Exercise(id, name, description, type, subtype, focus_prim, focus_sec)

    def __init__(self, id, name, description, type, subtype, focus_prim, focus_sec):
        self.id = id
        self.name = name
        self.description = description
        self.type = type
        self.subtype = subtype
        self.focus_prim = focus_prim
        self.focus_sec = focus_sec
        self.notes = ''
        self.video = ''
        self.translates = []

        self.validate()

    def validate(self):
        if self.type not in Exercise.TYPES:
            raise InvalidExerciseData("%s not a valid type"%self.type)

    def set_image_uuids(self, uuids):
        self.photo_start_id = uuids.start
        self.photo_end_id = uuids.end

    def __str__(self):
        args = (self.id, self.name, self.type)
        return "Exercise{id=%s, name=%s, type=%s}"%args

class InvalidExerciseData(Exception):
    pass

class Status:
    OK = 'OK'
    SKIPPED = 'SKIPPED'
    FAILED = 'FAILED'

if __name__ == "__main__":
    main()
