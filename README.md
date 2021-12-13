# ptflow-exercise-importer
> Batch import exercise data into a ptflow server instance

Uses a Google Sheet as a database for exercises and
a directory containing image files that are named using a specific naming scheme `{id}-.*.png`.

Supports resuming imports using a local bookkeeping file.

## Installing requirements
```
pip3 install --user --upgrade -r requirements.txt
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

## Getting started
Just visit Google Sheets API's [Python _Quickstart_ example](https://developers.google.com/sheets/api/quickstart/python) to quickly get a `credentials.json` you can put in the same directory as the script.
This will be used when authenticating with Google.

## Running the uploader on the given files

```
# You can also set some environment variables instead of specifying them on the command line:
# export PTFLOW_TOKEN=e061d6ee-752f-41f7-b73e-0a8f27522cd2
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


## Getting the token
Just log in as someone that is allowed to create exercises, open DevTools and get the value of the `ls.authorizationData` cookie, decode it and get the token value.

Here is my doing the last two steps after copy-pasting the value:
```
$ urldecode '%7B%22token%22%3A%225a7ef142ab835ed1719ae62b4708ca89%22%2C%22user%22%3A%7B%22id%22%3A%22aff54db8-3f73-41b7-b90e-065ceb386c00%22%2C%22first_name%22%3A%22Carl-Erik%22%2C%22last_name%22%3A%22Kopseng%22%2C%22email%22%3A%22foo%40bar.no%22%2C%22status%22%3A%22REGISTERED%22%2C%22photo%22%3Anull%2C%22photo_id%22%3Anull%2C%22role%22%3A%22ROLE_ADMIN%22%2C%22gender%22%3A%22MALE%22%2C%22birthday%22%3Anull%2C%22phone%22%3Anull%2C%22country%22%3Anull%2C%22country_code%22%3Anull%2C%22is_trial_available%22%3Atrue%2C%22invitedManager%22%3Anull%2C%22locked_currency%22%3Anull%7D%2C%22settings%22%3A%7B%22language%22%3Anull%2C%22timezone%22%3Anull%2C%22session_length%22%3A30%2C%22session_length_long%22%3A60%2C%22session_interval%22%3A15%2C%22include_logo%22%3Afalse%7D%7D' | jq .token
"5a7ef142ab835ed1719ae62b4708ca89"
```
