# ptflow-exercise-importer
> Batch import exercise data into a ptflow server instance

Uses a Google Sheet as a database (both input data and bookkeeping of running sessions) and
a directory containing image files that are named using a specific naming scheme `{id}-.*.png`.

Supports resuming imports by looking up session data in the Google Sheet (see `bookkeeping-id`).

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

## Running the uploader on the given files

```
# Set required environment variables
export PTFLOW_SESSION=e061d6ee-752f-41f7-b73e-0a8f27522cd2
export PTFLOW_SERVER=https://myserver.com:443

exercise-importer \
    --image-dir ~/exercises/PACK \
    --sheets-id 18_LuqnjAmVzAL6zQzJKjSWqGgPMLgYx0I_k3wV2I2xg \
    --bookkeeping-id myserver-2020-06-15
```
The `bookkeeping-id` is used to create a new worksheet (tab) within
the spreadsheet that will hold bookkeeping data, such as

- which exercises ids have been created
- which server created uuids correlate to which exercise image (step 1 or step 2)
- when it was successfully uploaded


