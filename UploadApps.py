import os
import xlrd
import requests
import sys
from time import sleep
import json
import argparse
import logging
import datetime
import time
import math

#Check if there is a log directory in the current working directory, and create one if there is not
if not os.path.exists('log'):
    os.makedirs('log')

#Within the log directory, check for a file named FodImport.log, and create one if there is not
if not os.path.exists('log/FodImport.log'):
    with open(os.path.join('log', 'FodImport.log'), 'w'):
        pass
    
#This instantiates a logger that will be used to track any applications and dynamic forms that don't correctly populate in FoD
logger      = logging.getLogger('FoDImport')
hdlr        = logging.FileHandler('log/FodImport.log')
formatter   = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

logger.setLevel(logging.INFO)
logger.addHandler(hdlr)

#Argument parser implemented mainly in the interest of creating a "Help" argument that presents the user information about how to use the script
parser = argparse.ArgumentParser(description="This is a tool to help upload applications to the Fortify on Demand evironment. Commands should be called in the following format:  *************\"UploadApps.py [path/file.xlsx] [key] [secret] -d\"*************  Only add the -d at the end if the import file that you're using includes columns for filling out the dynamic scan form for the first release on the application. This tool was provided with a spreadhsheet template which must be followed for it to funciton correctly, as well as a Word Document that describes each column in the spreadsheet.")

parser.add_argument('file', help="Provide the path and Excel file that you will be using for your import e.g. C:/Path/File.xlsx")
parser.add_argument('key', help="This is the API key provided by your Secruity Lead")
parser.add_argument('secret', help="This is the secret associated with the above key, also provided by your Security Lead")
parser.add_argument('-d', action='store_true', default=False, help="Add this flag if your import file includes dynamic scan form values, and you wish to fill out the dynamic form along with adding applications")
args = parser.parse_args()

def AddApplications(uploadFile, apiKey, apiSecret):
    #The AddApplications method is used for onboarding applications in to the Fortify on Demand environment, from an Excel spreadsheet
    #This method takes 3 arguments, the file with the data for upload, and the key and secret pair furnished for the FoD API

    workbook        = xlrd.open_workbook(uploadFile)
    appData         = workbook.sheet_by_name('Sheet1')
    numberRows      = appData.nrows
    applicationUrl  = 'https://api.ams.fortify.com/api/v3/applications'
    bearerToken     = GetToken(apiKey, apiSecret)   
    allUsers        = getUsers(bearerToken)
    
    if bearerToken != None:
        for i in range(1,numberRows):
            #Looping through the rows of the spreadsheet provided to get required application data
            appName         = appData.cell(i, 0).value
            businessCrit    = appData.cell(i, 1).value
            appType         = appData.cell(i, 2).value
            appType         = appType.replace(" ", "_")
            appType         = appType.replace("/", "_")
            releaseName     = appData.cell(i, 3).value
            sdlcStatus      = appData.cell(i, 4).value
            sdlcStatus      = sdlcStatus.replace('/Test','')
            ownerName       = appData.cell(i, 5).value
            ownerName       = ownerName.lower()
            ownerId         = str(allUsers[ownerName])
            dynamicData     = []
            customAttribute = False

            if (appData.cell(0, 19) and appData.cell(1,19).value != ""):
                customAttribute = True
                attributeArray = setCustomAttributeValue(appData.cell(0, 19).value, appData.cell(i, 19).value, bearerToken)
                attributeString = json.dumps(attributeArray)
            
            for n in range(6,21):
                #Loop through and pull out the data for the dynamic form and add it in to an object that will be passed to the method that fills out the form
                dynamicData.append(appData.cell(i, n).value)

            if customAttribute == False:
                payload = "{\r\n  \"applicationName\": \"" + appName + "\",\r\n  \"applicationType\": \"" + appType + "\",\r\n  \"releaseName\": \"" + releaseName + "\",\r\n  \"ownerId\": " + ownerId + ",\r\n  \"businessCriticalityType\": \"" + businessCrit + "\",\r\n  \"sdlcStatusType\": \"" + sdlcStatus + "\",\r\n}"
            else:
                payload = "{\r\n  \"applicationName\": \"" + appName + "\",\r\n  \"applicationType\": \"" + appType + "\",\r\n  \"releaseName\": \"" + releaseName + "\",\r\n  \"ownerId\": " + ownerId + ",\r\n  \"businessCriticalityType\": \"" + businessCrit + "\",\r\n  \"attributes\": " + attributeString + ",\r\n  \"sdlcStatusType\": \"" + sdlcStatus + "\",\r\n}"

            print(payload)

            headers = {
                'authorization': "Bearer " + bearerToken,
                'content-type': "application/json"
            }
            
            try:
                response = requests.request("Post", applicationUrl, data=payload, headers=headers)
                percentComplete = str(round(((i)/(numberRows-1))*100))
                print('Added ', percentComplete, '% of applications')
                print(response.text)
                ts = time.time()
                messageForLog = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') + " Application: " + str(appName) + " API Response: " + str(response.text)
                logger.info(messageForLog)
                responseJson = json.loads(response.text)
                releaseId = getReleaseId(responseJson['applicationId'], bearerToken)
                if args.d:
                    #args.d is the optional argument -d that when provided, sets the flag to true, meaning that we can expect there to be dynamic scan data for populating the dynamic scan form
                    populateDynamicForm(releaseId, bearerToken, dynamicData)
            except Exception as error:
                logger.error(error)
                
            sleep(30)
        
def GetToken(apiKey, apiSecret):
    #GetToken is the method used to authenticate to the FoD API, and extract the bearer token from the response
    authUrl = "https://api.ams.fortify.com/oauth/token"
    authorizationPayload = "scope=api-tenant&grant_type=client_credentials&client_id=" + apiKey + "&client_secret=" + apiSecret
    headers = {
        'content-type': "application/x-www-form-urlencoded",
        'cache-control': "no-cache"
    }
    response = requests.request("POST", authUrl, data=authorizationPayload, headers=headers)
    responseObject = json.loads(response.text)
    bearer = responseObject.get("access_token", "no token")
    
    if bearer != "no token":
        return responseObject['access_token']
    else:
        print(response.text)
    
    return None

def getUsers(bearerToken):
    #This method will pull all users from the system for the given tenant and create an object of key-value pairs that looks like: 
    #Username-User ID. This allows the organization to provide a user name (which is more human readable) in their spreadsheet
    #and we can use that to easily pull the User ID associated with that user name, giving us the required data to pass to the 
    #FoD API for the application owner
    userNameUrl = "https://api.ams.fortify.com/api/v3/users"
    headers = {
        'authorization': "Bearer " + bearerToken,
        'Accept': "application/json"
    }
    
    response = requests.request("GET", userNameUrl, headers=headers)
    allUserData = json.loads(response.text)
    numItems = len(allUserData['items'])
    numTotalUsers = allUserData['totalCount']
    allItems = allUserData['items']
    simplifiedUserData = {}
    
    #The API returns 50 users at a time, but also the number of total users in the tenant. The number of loops, therefore
    #is the number of users in the system/50, rounded up. That is, for 151 users, you will need to call the API 4 times 
    #151/50=3.02, this needs to be rounded up to get the last 1 user (1-50, 51-100, 100-150, 151)
    numLoops = int(math.ceil(numTotalUsers/50))
    
    for loop in range(0,numLoops):
        if (loop == 0):
            for n in range(0,numItems):
                thisUser = allItems[n]
                thisUserName = thisUser['userName'].lower()
                thisUserId = thisUser['userId']
                simplifiedUserData[thisUserName] = thisUserId
        else:
            #This increases the offset each time to get the next batch of users from the API
            offset = loop*50
            userNameUrl = "https://api.ams.fortify.com/api/v3/users?offset=" + str(offset)
            response = requests.request("GET", userNameUrl, headers=headers)
            allUserData = json.loads(response.text)
            allItems = allUserData['items']
            numItems = len(allUserData['items'])
            for z in range(0,numItems):
                thisUser = allItems[z]
                thisUserName = thisUser['userName']
                thisUserId = thisUser['userId']
                simplifiedUserData[thisUserName] = thisUserId
            
        
    return simplifiedUserData

def getReleaseId(appId, bearerToken):
    #When you create an application via the API, you are required to create a first release as well. But the API only returns the application ID
    #This method gets the ID of the release that you created so that you can use it to fill out the dynamic form (which is associated with releases
    #not applications)
    appIdString = str(appId)
    releaseDataUrl = "https://api.ams.fortify.com/api/v3/applications/" + appIdString + "/releases"
    headers = {
        'authorization': "Bearer " + bearerToken,
        'Accept': "application/json"
    }
    response = requests.request("GET", releaseDataUrl, headers=headers)
    fullResponse = json.loads(response.text)
    releaseId = fullResponse['items'][0]['releaseId']
    
    return releaseId

def populateDynamicForm(releaseId, bearerToken, dynamicData):
    #This method takes the dynamic form data from the user spreadsheet, parses it, and uses it to populated the dynamic form for our newly created release
    releaseIdString                         = str(releaseId)
    dynamicFormUrl                          = "https://api.ams.fortify.com/api/v3/releases/" + releaseIdString + "/dynamic-scans/scan-setup"
    siteUrl                                 = dynamicData[0]
    assessmentType                          = dynamicData[1]
    timeZone                                = dynamicData[2]
    environmentFace                         = dynamicData[3]
    repeatFreq                              = dynamicData[5]
    #The format of the site availability is specific, and the following method uses that to parse it in to the format that is required by the API
    siteAvail                               = generateSiteAvailability(dynamicData[6])
    subscription                            = dynamicData[12]
    exclusions                              = "" if dynamicData[4] == "" else setExclusions(dynamicData[4])
    restrictToDirectoryAndSubdirectories    = dynamicData[14]
    authMode                                = dynamicData[7]
    
    
    
    if restrictToDirectoryAndSubdirectories == "True" or restrictToDirectoryAndSubdirectories == "" or restrictToDirectoryAndSubdirectories == 1:
        restrictToDirectoryAndSubdirectories = "True"
    else:
        restrictToDirectoryAndSubdirectories = "False"
    
    
    if repeatFreq.lower() == 'do not repeat' or repeatFreq == "":
        repeatFreq = 'NoRepeat'
    else:
        repeatFreq = 'Monthly'
    
    if subscription == 1:
        entitlementType = "Subscription"
    elif subscription.lower() == 'true':
        entitlementType = "Subscription"
    else:
        entitlementType = "SingleScan"
    
    if assessmentType.lower() == 'dynamic':
        assessmentTypeId = 268
    else:
        assessmentTypeId = 269
        
    assessmentTypeId = str(assessmentTypeId)
        
    headers = {
        'authorization': "Bearer " + bearerToken,
        'content-type': "application/json"
    }
    
    if authMode == '' or authMode == 'NoAuthentication':
        dynamicFormPayload = "{\r\n  \"geoLocationId\": 1,\r\n  \"multiFactorAuth\": \"False\",\r\n  \"dynamicScanEnvironmentFacingType\": \"" + environmentFace + "\",\r\n  \"exclusionsList\": " + exclusions + ",\r\n  \"dynamicScanAuthenticationType\": \"NoAuthentication\",\r\n  \"dynamicSiteURL\": \"" + siteUrl + "\",\r\n  \"timeZone\": \"" + timeZone + "\",\r\n  \"blockout\": " + siteAvail + ",\r\n  \"repeatScheduleType\": \"" + repeatFreq + "\",\r\n  \"assessmentTypeId\":" + assessmentTypeId + ",\r\n  \"restrictToDirectoryAndSubdirectories\":\"" + restrictToDirectoryAndSubdirectories + "\",\r\n  \"entitlementFrequencyType\": \"" + entitlementType + "\"\r\n}"
    else:
        primaryUserName = dynamicData[8]
        primaryPass     = dynamicData[9]
        secondUserName  = dynamicData[10]
        secondPass      = dynamicData[11]
        
        dynamicFormPayload = "{\r\n  \"geoLocationId\": 1,\r\n  \"multiFactorAuth\": \"False\",\r\n  \"dynamicScanEnvironmentFacingType\": \"" + environmentFace + "\",\r\n  \"exclusionsList\": " + exclusions + ",\r\n  \"dynamicScanAuthenticationType\": \"" + authMode + "\",\r\n  \"primaryUserName\": \"" + primaryUserName + "\",\r\n  \"primaryUserPassword\": \"" + primaryPass + "\",\r\n  \"secondaryUserName\": \"" + secondUserName + "\",\r\n  \"secondaryUserPassword\": \"" + secondPass + "\",\r\n  \"dynamicSiteURL\": \"" + siteUrl + "\",\r\n  \"timeZone\": \"" + timeZone + "\",\r\n  \"blockout\": " + siteAvail + ",\r\n  \"repeatScheduleType\": \"" + repeatFreq + "\",\r\n  \"assessmentTypeId\":" + assessmentTypeId + ",\r\n  \"restrictToDirectoryAndSubdirectories\":\"" + restrictToDirectoryAndSubdirectories + "\",\r\n  \"entitlementFrequencyType\": \"" + entitlementType + "\"\r\n}"
        
    
    try:
        response = requests.request("Put", dynamicFormUrl, data=dynamicFormPayload, headers=headers)
        ts = time.time()
        messageForLog = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S') + " API Response while populating dynamic form: " + str(response.text)
        logger.info(messageForLog)
    except Exception as error:
        logger.error(error)
    
def generateSiteAvailability(availabilityCell):
    if availabilityCell == 'ALL DAY' or availabilityCell == "":
        # If they choose all day, the hourBlocks should all be set to True
        avail = [{'day': 'Sunday', 'hourBlocks': [{'hour': 0, 'checked': True}, {'hour': 1, 'checked': True},
                                                  {'hour': 2, 'checked': True}, {'hour': 3, 'checked': True},
                                                  {'hour': 4, 'checked': True}, {'hour': 5, 'checked': True},
                                                  {'hour': 6, 'checked': True}, {'hour': 7, 'checked': True},
                                                  {'hour': 8, 'checked': True}, {'hour': 9, 'checked': True},
                                                  {'hour': 10, 'checked': True}, {'hour': 11, 'checked': True},
                                                  {'hour': 12, 'checked': True}, {'hour': 13, 'checked': True},
                                                  {'hour': 14, 'checked': True}, {'hour': 15, 'checked': True},
                                                  {'hour': 16, 'checked': True}, {'hour': 17, 'checked': True},
                                                  {'hour': 18, 'checked': True}, {'hour': 19, 'checked': True},
                                                  {'hour': 20, 'checked': True}, {'hour': 21, 'checked': True},
                                                  {'hour': 22, 'checked': True}, {'hour': 23, 'checked': True}]},
                 {'day': 'Monday', 'hourBlocks': [{'hour': 0, 'checked': True}, {'hour': 1, 'checked': True},
                                                  {'hour': 2, 'checked': True}, {'hour': 3, 'checked': True},
                                                  {'hour': 4, 'checked': True}, {'hour': 5, 'checked': True},
                                                  {'hour': 6, 'checked': True}, {'hour': 7, 'checked': True},
                                                  {'hour': 8, 'checked': True}, {'hour': 9, 'checked': True},
                                                  {'hour': 10, 'checked': True}, {'hour': 11, 'checked': True},
                                                  {'hour': 12, 'checked': True}, {'hour': 13, 'checked': True},
                                                  {'hour': 14, 'checked': True}, {'hour': 15, 'checked': True},
                                                  {'hour': 16, 'checked': True}, {'hour': 17, 'checked': True},
                                                  {'hour': 18, 'checked': True}, {'hour': 19, 'checked': True},
                                                  {'hour': 20, 'checked': True}, {'hour': 21, 'checked': True},
                                                  {'hour': 22, 'checked': True}, {'hour': 23, 'checked': True}]},
                 {'day': 'Tuesday', 'hourBlocks': [{'hour': 0, 'checked': True}, {'hour': 1, 'checked': True},
                                                   {'hour': 2, 'checked': True}, {'hour': 3, 'checked': True},
                                                   {'hour': 4, 'checked': True}, {'hour': 5, 'checked': True},
                                                   {'hour': 6, 'checked': True}, {'hour': 7, 'checked': True},
                                                   {'hour': 8, 'checked': True}, {'hour': 9, 'checked': True},
                                                   {'hour': 10, 'checked': True}, {'hour': 11, 'checked': True},
                                                   {'hour': 12, 'checked': True}, {'hour': 13, 'checked': True},
                                                   {'hour': 14, 'checked': True}, {'hour': 15, 'checked': True},
                                                   {'hour': 16, 'checked': True}, {'hour': 17, 'checked': True},
                                                   {'hour': 18, 'checked': True}, {'hour': 19, 'checked': True},
                                                   {'hour': 20, 'checked': True}, {'hour': 21, 'checked': True},
                                                   {'hour': 22, 'checked': True}, {'hour': 23, 'checked': True}]},
                 {'day': 'Wednesday', 'hourBlocks': [{'hour': 0, 'checked': True}, {'hour': 1, 'checked': True},
                                                     {'hour': 2, 'checked': True}, {'hour': 3, 'checked': True},
                                                     {'hour': 4, 'checked': True}, {'hour': 5, 'checked': True},
                                                     {'hour': 6, 'checked': True}, {'hour': 7, 'checked': True},
                                                     {'hour': 8, 'checked': True}, {'hour': 9, 'checked': True},
                                                     {'hour': 10, 'checked': True}, {'hour': 11, 'checked': True},
                                                     {'hour': 12, 'checked': True}, {'hour': 13, 'checked': True},
                                                     {'hour': 14, 'checked': True}, {'hour': 15, 'checked': True},
                                                     {'hour': 16, 'checked': True}, {'hour': 17, 'checked': True},
                                                     {'hour': 18, 'checked': True}, {'hour': 19, 'checked': True},
                                                     {'hour': 20, 'checked': True}, {'hour': 21, 'checked': True},
                                                     {'hour': 22, 'checked': True}, {'hour': 23, 'checked': True}]},
                 {'day': 'Thursday', 'hourBlocks': [{'hour': 0, 'checked': True}, {'hour': 1, 'checked': True},
                                                    {'hour': 2, 'checked': True}, {'hour': 3, 'checked': True},
                                                    {'hour': 4, 'checked': True}, {'hour': 5, 'checked': True},
                                                    {'hour': 6, 'checked': True}, {'hour': 7, 'checked': True},
                                                    {'hour': 8, 'checked': True}, {'hour': 9, 'checked': True},
                                                    {'hour': 10, 'checked': True}, {'hour': 11, 'checked': True},
                                                    {'hour': 12, 'checked': True}, {'hour': 13, 'checked': True},
                                                    {'hour': 14, 'checked': True}, {'hour': 15, 'checked': True},
                                                    {'hour': 16, 'checked': True}, {'hour': 17, 'checked': True},
                                                    {'hour': 18, 'checked': True}, {'hour': 19, 'checked': True},
                                                    {'hour': 20, 'checked': True}, {'hour': 21, 'checked': True},
                                                    {'hour': 22, 'checked': True}, {'hour': 23, 'checked': True}]},
                 {'day': 'Friday', 'hourBlocks': [{'hour': 0, 'checked': True}, {'hour': 1, 'checked': True},
                                                  {'hour': 2, 'checked': True}, {'hour': 3, 'checked': True},
                                                  {'hour': 4, 'checked': True}, {'hour': 5, 'checked': True},
                                                  {'hour': 6, 'checked': True}, {'hour': 7, 'checked': True},
                                                  {'hour': 8, 'checked': True}, {'hour': 9, 'checked': True},
                                                  {'hour': 10, 'checked': True}, {'hour': 11, 'checked': True},
                                                  {'hour': 12, 'checked': True}, {'hour': 13, 'checked': True},
                                                  {'hour': 14, 'checked': True}, {'hour': 15, 'checked': True},
                                                  {'hour': 16, 'checked': True}, {'hour': 17, 'checked': True},
                                                  {'hour': 18, 'checked': True}, {'hour': 19, 'checked': True},
                                                  {'hour': 20, 'checked': True}, {'hour': 21, 'checked': True},
                                                  {'hour': 22, 'checked': True}, {'hour': 23, 'checked': True}]},
                 {'day': 'Saturday', 'hourBlocks': [{'hour': 0, 'checked': True}, {'hour': 1, 'checked': True},
                                                    {'hour': 2, 'checked': True}, {'hour': 3, 'checked': True},
                                                    {'hour': 4, 'checked': True}, {'hour': 5, 'checked': True},
                                                    {'hour': 6, 'checked': True}, {'hour': 7, 'checked': True},
                                                    {'hour': 8, 'checked': True}, {'hour': 9, 'checked': True},
                                                    {'hour': 10, 'checked': True}, {'hour': 11, 'checked': True},
                                                    {'hour': 12, 'checked': True}, {'hour': 13, 'checked': True},
                                                    {'hour': 14, 'checked': True}, {'hour': 15, 'checked': True},
                                                    {'hour': 16, 'checked': True}, {'hour': 17, 'checked': True},
                                                    {'hour': 18, 'checked': True}, {'hour': 19, 'checked': True},
                                                    {'hour': 20, 'checked': True}, {'hour': 21, 'checked': True},
                                                    {'hour': 22, 'checked': True}, {'hour': 23, 'checked': True}]}]

        availString = json.dumps(avail)
        return availString
    else:
        # If they provide specific hours that their site is available, step one is to create an object where all hours are set to unavailable, and then
        # use their data to specify which hours the site is available. Note that we get the times from the user in military time. If the user wants to
        # have the site available from 8AM to 5PM, they would provide 0800 to 1700. The API accepts this data as hour 0, hour 1, all the way to hour 23.
        # To convert, we simply strip the zeros and subtract 1 to get the correct hours.
        avail = [{'day': 'Sunday', 'hourBlocks': [{'hour': 0, 'checked': False}, {'hour': 1, 'checked': False},
                                                  {'hour': 2, 'checked': False}, {'hour': 3, 'checked': False},
                                                  {'hour': 4, 'checked': False}, {'hour': 5, 'checked': False},
                                                  {'hour': 6, 'checked': False}, {'hour': 7, 'checked': False},
                                                  {'hour': 8, 'checked': False}, {'hour': 9, 'checked': False},
                                                  {'hour': 10, 'checked': False}, {'hour': 11, 'checked': False},
                                                  {'hour': 12, 'checked': False}, {'hour': 13, 'checked': False},
                                                  {'hour': 14, 'checked': False}, {'hour': 15, 'checked': False},
                                                  {'hour': 16, 'checked': False}, {'hour': 17, 'checked': False},
                                                  {'hour': 18, 'checked': False}, {'hour': 19, 'checked': False},
                                                  {'hour': 20, 'checked': False}, {'hour': 21, 'checked': False},
                                                  {'hour': 22, 'checked': False}, {'hour': 23, 'checked': False}]},
                 {'day': 'Monday', 'hourBlocks': [{'hour': 0, 'checked': False}, {'hour': 1, 'checked': False},
                                                  {'hour': 2, 'checked': False}, {'hour': 3, 'checked': False},
                                                  {'hour': 4, 'checked': False}, {'hour': 5, 'checked': False},
                                                  {'hour': 6, 'checked': False}, {'hour': 7, 'checked': False},
                                                  {'hour': 8, 'checked': False}, {'hour': 9, 'checked': False},
                                                  {'hour': 10, 'checked': False}, {'hour': 11, 'checked': False},
                                                  {'hour': 12, 'checked': False}, {'hour': 13, 'checked': False},
                                                  {'hour': 14, 'checked': False}, {'hour': 15, 'checked': False},
                                                  {'hour': 16, 'checked': False}, {'hour': 17, 'checked': False},
                                                  {'hour': 18, 'checked': False}, {'hour': 19, 'checked': False},
                                                  {'hour': 20, 'checked': False}, {'hour': 21, 'checked': False},
                                                  {'hour': 22, 'checked': False}, {'hour': 23, 'checked': False}]},
                 {'day': 'Tuesday', 'hourBlocks': [{'hour': 0, 'checked': False}, {'hour': 1, 'checked': False},
                                                   {'hour': 2, 'checked': False}, {'hour': 3, 'checked': False},
                                                   {'hour': 4, 'checked': False}, {'hour': 5, 'checked': False},
                                                   {'hour': 6, 'checked': False}, {'hour': 7, 'checked': False},
                                                   {'hour': 8, 'checked': False}, {'hour': 9, 'checked': False},
                                                   {'hour': 10, 'checked': False}, {'hour': 11, 'checked': False},
                                                   {'hour': 12, 'checked': False}, {'hour': 13, 'checked': False},
                                                   {'hour': 14, 'checked': False}, {'hour': 15, 'checked': False},
                                                   {'hour': 16, 'checked': False}, {'hour': 17, 'checked': False},
                                                   {'hour': 18, 'checked': False}, {'hour': 19, 'checked': False},
                                                   {'hour': 20, 'checked': False}, {'hour': 21, 'checked': False},
                                                   {'hour': 22, 'checked': False}, {'hour': 23, 'checked': False}]},
                 {'day': 'Wednesday', 'hourBlocks': [{'hour': 0, 'checked': False}, {'hour': 1, 'checked': False},
                                                     {'hour': 2, 'checked': False}, {'hour': 3, 'checked': False},
                                                     {'hour': 4, 'checked': False}, {'hour': 5, 'checked': False},
                                                     {'hour': 6, 'checked': False}, {'hour': 7, 'checked': False},
                                                     {'hour': 8, 'checked': False}, {'hour': 9, 'checked': False},
                                                     {'hour': 10, 'checked': False}, {'hour': 11, 'checked': False},
                                                     {'hour': 12, 'checked': False}, {'hour': 13, 'checked': False},
                                                     {'hour': 14, 'checked': False}, {'hour': 15, 'checked': False},
                                                     {'hour': 16, 'checked': False}, {'hour': 17, 'checked': False},
                                                     {'hour': 18, 'checked': False}, {'hour': 19, 'checked': False},
                                                     {'hour': 20, 'checked': False}, {'hour': 21, 'checked': False},
                                                     {'hour': 22, 'checked': False}, {'hour': 23, 'checked': False}]},
                 {'day': 'Thursday', 'hourBlocks': [{'hour': 0, 'checked': False}, {'hour': 1, 'checked': False},
                                                    {'hour': 2, 'checked': False}, {'hour': 3, 'checked': False},
                                                    {'hour': 4, 'checked': False}, {'hour': 5, 'checked': False},
                                                    {'hour': 6, 'checked': False}, {'hour': 7, 'checked': False},
                                                    {'hour': 8, 'checked': False}, {'hour': 9, 'checked': False},
                                                    {'hour': 10, 'checked': False}, {'hour': 11, 'checked': False},
                                                    {'hour': 12, 'checked': False}, {'hour': 13, 'checked': False},
                                                    {'hour': 14, 'checked': False}, {'hour': 15, 'checked': False},
                                                    {'hour': 16, 'checked': False}, {'hour': 17, 'checked': False},
                                                    {'hour': 18, 'checked': False}, {'hour': 19, 'checked': False},
                                                    {'hour': 20, 'checked': False}, {'hour': 21, 'checked': False},
                                                    {'hour': 22, 'checked': False}, {'hour': 23, 'checked': False}]},
                 {'day': 'Friday', 'hourBlocks': [{'hour': 0, 'checked': False}, {'hour': 1, 'checked': False},
                                                  {'hour': 2, 'checked': False}, {'hour': 3, 'checked': False},
                                                  {'hour': 4, 'checked': False}, {'hour': 5, 'checked': False},
                                                  {'hour': 6, 'checked': False}, {'hour': 7, 'checked': False},
                                                  {'hour': 8, 'checked': False}, {'hour': 9, 'checked': False},
                                                  {'hour': 10, 'checked': False}, {'hour': 11, 'checked': False},
                                                  {'hour': 12, 'checked': False}, {'hour': 13, 'checked': False},
                                                  {'hour': 14, 'checked': False}, {'hour': 15, 'checked': False},
                                                  {'hour': 16, 'checked': False}, {'hour': 17, 'checked': False},
                                                  {'hour': 18, 'checked': False}, {'hour': 19, 'checked': False},
                                                  {'hour': 20, 'checked': False}, {'hour': 21, 'checked': False},
                                                  {'hour': 22, 'checked': False}, {'hour': 23, 'checked': False}]},
                 {'day': 'Saturday', 'hourBlocks': [{'hour': 0, 'checked': False}, {'hour': 1, 'checked': False},
                                                    {'hour': 2, 'checked': False}, {'hour': 3, 'checked': False},
                                                    {'hour': 4, 'checked': False}, {'hour': 5, 'checked': False},
                                                    {'hour': 6, 'checked': False}, {'hour': 7, 'checked': False},
                                                    {'hour': 8, 'checked': False}, {'hour': 9, 'checked': False},
                                                    {'hour': 10, 'checked': False}, {'hour': 11, 'checked': False},
                                                    {'hour': 12, 'checked': False}, {'hour': 13, 'checked': False},
                                                    {'hour': 14, 'checked': False}, {'hour': 15, 'checked': False},
                                                    {'hour': 16, 'checked': False}, {'hour': 17, 'checked': False},
                                                    {'hour': 18, 'checked': False}, {'hour': 19, 'checked': False},
                                                    {'hour': 20, 'checked': False}, {'hour': 21, 'checked': False},
                                                    {'hour': 22, 'checked': False}, {'hour': 23, 'checked': False}]}]

        if availabilityCell.find('Sunday') != -1:
            dayStart = availabilityCell.find('Sunday')
            dayEnd = availabilityCell.find(';', dayStart)
            timeStart = availabilityCell.find(':', dayStart)
            timeSplit = availabilityCell.find('-', dayStart)
            startTime = availabilityCell[timeStart + 1:timeSplit]
            endTime = availabilityCell[timeSplit + 1:dayEnd]
            startTime = startTime[0:2]
            endTime = endTime[0:2]
            try:
                startTime = int(startTime)
            except:
                startTime = 0
            endTime = int(endTime)
            endTime = endTime
            for time in range(startTime, endTime):
                avail[0]['hourBlocks'][time]['checked'] = True

        if availabilityCell.find('Monday') != -1:
            dayStart = availabilityCell.find('Monday')
            dayEnd = availabilityCell.find(';', dayStart)
            timeStart = availabilityCell.find(':', dayStart)
            timeSplit = availabilityCell.find('-', dayStart)
            startTime = availabilityCell[timeStart + 1:timeSplit]
            endTime = availabilityCell[timeSplit + 1:dayEnd]
            startTime = startTime[0:2]
            endTime = endTime[0:2]
            try:
                startTime = int(startTime)
            except:
                startTime = 0
            endTime = int(endTime)
            endTime = endTime
            for time in range(startTime, endTime):
                avail[1]['hourBlocks'][time]['checked'] = True

        if availabilityCell.find('Tuesday') != -1:
            dayStart = availabilityCell.find('Tuesday')
            dayEnd = availabilityCell.find(';', dayStart)
            timeStart = availabilityCell.find(':', dayStart)
            timeSplit = availabilityCell.find('-', dayStart)
            startTime = availabilityCell[timeStart + 1:timeSplit]
            endTime = availabilityCell[timeSplit + 1:dayEnd]
            startTime = startTime[0:2]
            endTime = endTime[0:2]
            try:
                startTime = int(startTime)
            except:
                startTime = 0
            endTime = int(endTime)
            endTime = endTime
            for time in range(startTime, endTime):
                avail[2]['hourBlocks'][time]['checked'] = True

        if availabilityCell.find('Wednesday') != -1:
            dayStart = availabilityCell.find('Wednesday')
            dayEnd = availabilityCell.find(';', dayStart)
            timeStart = availabilityCell.find(':', dayStart)
            timeSplit = availabilityCell.find('-', dayStart)
            startTime = availabilityCell[timeStart + 1:timeSplit]
            endTime = availabilityCell[timeSplit + 1:dayEnd]
            startTime = startTime[0:2]
            endTime = endTime[0:2]
            try:
                startTime = int(startTime)
            except:
                startTime = 0
            endTime = int(endTime)
            endTime = endTime
            for time in range(startTime, endTime):
                avail[3]['hourBlocks'][time]['checked'] = True

        if availabilityCell.find('Thursday') != -1:
            dayStart = availabilityCell.find('Thursday')
            dayEnd = availabilityCell.find(';', dayStart)
            timeStart = availabilityCell.find(':', dayStart)
            timeSplit = availabilityCell.find('-', dayStart)
            startTime = availabilityCell[timeStart + 1:timeSplit]
            endTime = availabilityCell[timeSplit + 1:dayEnd]
            startTime = startTime[0:2]
            endTime = endTime[0:2]
            try:
                startTime = int(startTime)
            except:
                startTime = 0
            endTime = int(endTime)
            endTime = endTime
            for time in range(startTime, endTime):
                avail[4]['hourBlocks'][time]['checked'] = True

        if availabilityCell.find('Friday') != -1:
            dayStart = availabilityCell.find('Friday')
            dayEnd = availabilityCell.find(';', dayStart)
            timeStart = availabilityCell.find(':', dayStart)
            timeSplit = availabilityCell.find('-', dayStart)
            startTime = availabilityCell[timeStart + 1:timeSplit]
            endTime = availabilityCell[timeSplit + 1:dayEnd]
            startTime = startTime[0:2]
            endTime = endTime[0:2]
            try:
                startTime = int(startTime)
            except:
                startTime = 0
            endTime = int(endTime)
            endTime = endTime
            for time in range(startTime, endTime):
                avail[5]['hourBlocks'][time]['checked'] = True

        if availabilityCell.find('Saturday') != -1:
            dayStart = availabilityCell.find('Saturday')
            dayEnd = availabilityCell.find(';', dayStart)
            timeStart = availabilityCell.find(':', dayStart)
            timeSplit = availabilityCell.find('-', dayStart)
            startTime = availabilityCell[timeStart + 1:timeSplit]
            endTime = availabilityCell[timeSplit + 1:dayEnd]
            startTime = startTime[0:2]
            endTime = endTime[0:2]
            try:
                startTime = int(startTime)
            except:
                startTime = 0
            endTime = int(endTime)
            endTime = endTime
            for time in range(startTime, endTime):
                avail[6]['hourBlocks'][time]['checked'] = True

        availString = json.dumps(avail)
        return availString
    
def setExclusions(exclusionValues):
    #Eclusions are provided in the format of a list of semi-colon separated strings by the user. This then splits that list to create an array
    #and then formas them in to a list of objects ["value":"Exclusion String 1", "value":"Exclusion String 2"..."value":"Exclusion String n"]
    #as is expected by the API.
    exclusionList = exclusionValues.split(';')
    exclusionsForFod = []
    
    for index in range(0,len(exclusionList)):
        thisExclusion = {'value':exclusionList[index]}
        exclusionsForFod.append(thisExclusion)
        
    exclusionsForFodString = json.dumps(exclusionsForFod)
    return exclusionsForFodString

def setCustomAttributeValue(attributeName, givenAttributeValue, bearerToken):
    url = "https://api.ams.fortify.com/api/v3/attributes"
    groupNameForQuery = "name:" + attributeName
    querystring = {"filters":groupNameForQuery}
    attributeArray = []
    thisAttribute = {}
    attributeId = 0

    headers = {
        'authorization': "Bearer " + bearerToken,
        'accept': "application/json"
        }
    response = requests.request("GET", url, headers=headers, params=querystring)
    
    attributeOptions = json.loads(response.text)

    numberOfAttributes = len(attributeOptions['items'])

    for x in range(0, numberOfAttributes):
        if attributeOptions['items'][x]['name'] == attributeName:
            pickListValues = attributeOptions['items'][x]['picklistValues']
            attributeNameId = attributeOptions['items'][x]['id']

    
    for optionNum in range(0,len(pickListValues)):
        if pickListValues[optionNum]['name'] == givenAttributeValue:
            attributeId = pickListValues[optionNum]['id']
    
    thisAttribute['id'] = attributeNameId
    thisAttribute['value'] = attributeId
    attributeArray.append(thisAttribute)
    return attributeArray
    
    
    
AddApplications(sys.argv[1], sys.argv[2], sys.argv[3])