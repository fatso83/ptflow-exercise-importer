# ptflow-exercise-importer
> Batch import exercise data into a ptflow server instance

Uses a Google Sheet as a database for exercises and
a directory containing image files that are named using a specific naming scheme `{id}-.*.png`.

Supports resuming imports using a local bookkeeping file.

## Installing requirements
```
pip install --user --upgrade -r requirements.txt
```

## Preparing the files

- Download zip file of all exercises
- Unpack embedded "pack" zip file 
- Rename files, removing the 1101 postfix to align the ids with that in the spreadsheet

Example CLI usage
```
# Unzip zip file of all exercies, downloaded from shared folder "Øvelser" in Google Drive
unzip -d exercises Øvelser-20200503T205554Z-001.zip
cd exercises 
# Unzip embedded zip file
unzip -d PACK STEPS-pack.zip
find PACK -print0 -name '*1101-*.png' |  xargs -0  rename -s '1101-' '-' 
```

## Installing requirements
```
pip install --upgrade pyyaml google-api-python-client google-auth-httplib2 google-auth-oauthlib  --user
```

## Getting started
Just visit Google Sheets API's [Python _Quickstart_ example](https://developers.google.com/sheets/api/quickstart/python) to quickly get a `credentials.json` you can put in the same directory as the script.
This will be used when authenticating with Google.

## Running the uploader on the given files

```
# You can also set some environment variables instead of specifying them on the command line:
# export PTFLOW_SESSION=e061d6ee-752f-41f7-b73e-0a8f27522cd2
# export PTFLOW_SERVER=https://myserver.com:443

python3 exercise-importer.py \
    --sheets-id 18_LuqnjAmVzAL6zQzJKjSWqGgPMLgYx0I_k3wV2I2xg \
	--image-dir ~/ptflow-exercises/PACK/ \
    --bookkeeping-id myserver-2020-06-15 \
	--server http://localhost:8000  \
	--session-token 28956340ba9c7e25b49085b4d273522b
```
The `bookkeeping-id` is used to create a file that will hold bookkeeping data, such as

- which exercises ids have been created
- which server created uuids correlate to which exercise 
- when it was successfully uploaded


