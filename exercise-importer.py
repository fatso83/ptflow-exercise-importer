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

# for heavy http logging
# import http.client as http_client
# http_client.HTTPConnection.debuglevel = 1

# The ID and range of a sample spreadsheet.
SPREADSHEET_ID = "1oJ2bth6yuyRnEQ9h66Iefah0pDlbZIDwsK7cNdC8Zs8" # ptflow master
RANGE_NAME = "ILLUSTRATIONS!B2:J"

# For development using mock data
use_fakes = False

logging.basicConfig(
        filename="import.log", filemode="w", 
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
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

argparser = argparse.ArgumentParser()
argparser.add_argument(
        "--image-dir", type=str, required=True,
        help="A directory containing image files that are named using a specific naming scheme: {id}-.*.png")
argparser.add_argument(
        "--sheets-id", type=str, 
        help="The id of the Google Sheet containing exercise data (i.e. '18_LuqnjAmVzAL6zQzJKjSWqGgPMLgYx0I_k3wV2I2xg'")
argparser.add_argument(
        "--bookkeeping-id", type=str, required=True,
        help="Used to keep tabs on what data has been uploaded. Makes it possible to resume a previous upload, avoiding duplicated uploads")
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
    if not os.path.isdir("data"):
        os.mkdir("data")
    oplog_filename = "data/%s-log.yml"%parsed.bookkeeping_id

    uploads = create_upload_map(oplog_filename)
    if len(uploads.keys()):
        logger.info("Continuing uploads from previous session (%s uploads so far) ...", len(uploads.keys()))

    logger.debug("Starting to loop through values from spreadsheet")
    prioritized=[1,2]
    filtered = [row for row in values if int(row[0]) in prioritized]
    logger.info("Skipping %d exercises that are not priority %s", len(values)-len(filtered), prioritized)

    for row in filtered:
        try:
            exercise = Exercise.from_row(row[1:])
            logger.debug(str(exercise))
        except InvalidExerciseData as e:
            logger.info("Invalid exercise data: {0}".format(e))
            result = LoggedExercise.from_failure(row[0], Status.SKIPPED, str(e))
            add_result_to_oplog(result, oplog_filename)
            print(row)
            sys.exit(1)
            continue

        try:
            images = get_images(image_dir, exercise.id)

            # check if already uploaded - return early if so
            if exercise.id in uploads and uploads[exercise.id].status == Status.OK:
                logger.info("Already uploaded exercise '%s' (server id: %s). Skipping.", exercise.id, uploads[exercise.id].uuid)
                continue

            result = upload_exercise(exercise, images, uploader)
            add_result_to_oplog(result, oplog_filename)

        except NonConformingImagesException as exception:
            logger.warning(exception)
            result = LoggedExercise.from_failure(exercise.id, Status.SKIPPED, str(exception))
            add_result_to_oplog(result, oplog_filename)


    summary = create_summary(oplog_filename, values)
    difference_ids = summary[3]
    print("\nFinished uploading!")
    print(80*"-")
    print("Total number of exercises in Google Sheet: %d" % len(values))
    print("Total number of exercises processed: %d" % summary[0])
    num_dif = len(difference_ids)
    if num_dif > 0 and num_dif < 10:
        print("The ids that are missing from one or the other are " + str(difference_ids))
    elif num_dif > 10:
        print("There are more than %d ids from one or the other!"%num_dif)
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

    logger.info("Uploading exercise %s", exercise.id)
    try:
        exercise.uuid = uploader.upload_exercise(exercise)
    except InvalidRequestException as e:
        return LoggedExercise.from_failure(exercise.id, Status.FAILED, str(e))

    logger.debug("Uploading %s images for exercise %s", len(images), exercise.id)
    img_uuid_start = uploader.upload_image(images[0])
    img_uuid_end = uploader.upload_image(images[1]) if len(images) > 1 else ''
    image_uuids = { 
            'start': img_uuid_start,
            'end': img_uuid_end }
    logger.debug("Got image uuids: %s"%str(image_uuids))
    exercise.set_image_uuids(image_uuids)

    # update the now existing exercise using images and the embedded uuid
    uploader.update_exercise(exercise)

    timestamp = datetime.datetime.utcnow()
    return LoggedExercise(exercise.id, exercise.uuid, Status.OK, timestamp, images, image_uuids)

def uuid_string():
    return str(uuid.uuid4())

class RealUploader:

    def __init__(self, server, bearer_token):
        logger.debug("Initialized uploader with bearer token {0}".format(bearer_token))
        self.server = server
        self.bearer_token = bearer_token

    def default_headers(self):
        return {
                'Authorization': 'Bearer ' + self.bearer_token,
                'Accept': 'application/json'
                }

    def upload_image(self, image):
        """See ApiImageController
         --> { image:'21fd2176-f3b9-11ea-ae83-00155d1775a6' }
        """

             

        url = self.server + "/api/1/images"
        headers = self.default_headers()
        headers['content-type'] = 'image/png'

        # This is not needed on latest development branch
        # See https://stackoverflow.com/questions/63843865/wrong-content-length-when-sending-a-file/63854311#63854311
        headers['Content-Disposition'] = 'form-data; name="not-used"; filename="also-ignored.jpg"'

        logger.debug("Image filesize: {0}".format(os.stat(image).st_size))

        with open(image, 'rb') as imagefile:
            # POST image
            r = requests.post(url, headers=headers, data=imagefile, timeout = 5.0)
            logger.debug("Request headers for /api/1/images: {0}".format(r.request.headers))
            logger.debug("Response headers for /api/1/images: {0}".format(r.headers))

        json_response = r.json()
        if r.status_code is not 201:
            logger.warning("Failed in uploading image: {0}".format(json_response))
            raise InvalidRequestException(str(json_response))

        return json_response['image']['id']

    def update_exercise(self, exercise):
        if not exercise.uuid:
            raise InvalidExerciseData("Trying to update exercise without a pre-set uuid does not make sense")
        self.upload_exercise(exercise, update = True)

    def upload_exercise(self, exercise, update = False):
        """See docs for ApiExerciseController.createAction"""

        headers = self.default_headers()
        headers['Content-Type'] = 'application/json'

        if update:
            r = requests.put(
                    self.server + "/api/1/exercises/"+exercise.uuid, 
                    json = exercise.__dict__,
                    timeout = 5.0,
                    headers = headers )
            json_response = r.json()
            if r.status_code is not 200:
                logger.warning("Failed in updating exercise: {0}".format(json_response))
                raise InvalidRequestException(str(json_response))
        else:
            r = requests.post(
                    self.server + "/api/1/exercises", 
                    json = exercise.__dict__,
                    timeout = 5.0,
                    headers = headers )

            json_response = r.json()
            if r.status_code is not 201:
                logger.warning("Failed in creating exercise: {0}".format(json_response))
                raise InvalidRequestException(str(json_response))

        logger.debug("Exercise response: {0}".format(r))
        logger.debug("Response body: {0}".format(r.content))

        return json_response['exercise']['id']

class InvalidRequestException(Exception):
    pass

class FakeUploader:

    def upload_image(self, image):
        logger.debug("Fake image upload of " + image)
        time.sleep(1)
        return uuid_string()


    def upload_exercise(self, exercise):
        logger.debug("Fake exercise upload of " + exercise.id)
        time.sleep(2)
        return uuid_string()

    def update_exercise(self, exercise):
        self.upload_exercise(exercise)

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
            raise TooManyImagesException("%s images found for %s. Require only two for start/end"%(len(image_list), exercise_id))

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

    #logger.warning("TODO:remove limit ")
    return result.get("values", []) #[0:5]

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

    TYPES = ["STRENGTH", "WEIGHT", "CARDIO", "MOBILITY", "CORE", "YOGA" ]
    FOCUSES = [ "ABS", "BACK", "BICEPS", "CHEST", "FOREARMS", "FULLBODY", "GLUTES", "LEGS", "SHOULDERS", "TRICEPS" ]

    @staticmethod
    def from_row(row):
        """Basically a factory method: spreadsheet row to instance"""

        def convert_focus(focus):
            if (focus == "Full Body"):
                return "FULLBODY"
            return focus.upper()

        def convert_type(literal_type):
            typeMap = { 'Body Weight': 'WEIGHT' }
            if literal_type in typeMap:
                return typeMap[literal_type]
            else: 
                # fallback 
                # if it is wrong, it will fail in validate()
                return literal_type.upper()


        required_length = 8 # C2-J2
        list_length = len(row)
        missing_vals = required_length-list_length

        if missing_vals > 0: 
            row.extend(['']*missing_vals)

        id = row[0]
        name = row[1]
        description = row[3]
        type = convert_type(row[4])

        focus_prim = convert_focus(row[6])
        focus_sec = convert_focus(row[7]) 

        notes = '' # unused
        equipment = ''

        # Ref https://pt-flow.slack.com/archives/GQ2QX4HNJ/p1600112328050900
        return Exercise(id, name, description, type, equipment, '', '')

    def __init__(self, id, name, description, type, equipment, focus_prim, focus_sec):
        self.id = id # this is the simple id from the spreadsheet, not the UUID from server
        self.uuid = '' # this is the server UUID
        self.name = name
        self.description = description
        self.type = type
        self.equipment= equipment
        self.focus_prim = focus_prim
        self.focus_sec = focus_sec
        self.notes = ''
        self.video = ''
        self.translates = []

        self.validate()

    def validate(self):

        php_file = 'src/PETE/BackendBundle/Entity/Exercise.php'
        if self.type not in Exercise.TYPES:
            raise InvalidExerciseData("'%s' not a valid type. Refer to %s"%(self.type, php_file))
        if self.focus_prim and self.focus_prim not in Exercise.FOCUSES:
            raise InvalidExerciseData("'%s' not a valid focus. Refer to %s. Valid: %s"%(self.focus_prim, php_file, ", ".join(Exercise.FOCUSES)))
        if self.focus_sec and self.focus_sec not in Exercise.FOCUSES:
            raise InvalidExerciseData("'%s' not a valid focus. Refer to %s. Valid: %s"%(self.focus_sec, php_file, ", ".join(Exercise.FOCUSES)))
        if self.type is 'STRENGTH' and self.subtype not in Exercise.SUBTYPES:
            raise InvalidExerciseData("'%s' not a valid subtype. Refer to %s. Valid: %s"%(self.focus_sec, php_file, ", ".join(Exercise.SUBTYPES)))

    def set_image_uuids(self, uuids):
        self.photo_start_id = uuids['start']
        self.photo_end_id = uuids['end']

    def __str__(self):
        args = (self.id, self.name, self.type, self.focus_prim)
        return "Exercise{id=%s, name=%s, type=%s, focus_prim=%s}"%args

class InvalidExerciseData(Exception):
    pass

class Status:
    OK = 'OK'
    SKIPPED = 'SKIPPED'
    FAILED = 'FAILED'

if __name__ == "__main__":
    main()
