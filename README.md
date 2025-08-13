# Gmail Unsubscribe Tool

A Python script that automatically finds and processes unsubscribe links from Gmail messages. This tool can help you clean up your inbox by unsubscribing from mailing lists and newsletters.

## Prerequisites

- Python 3.7+
- Gmail account
- Google Cloud Project with Gmail API enabled

## Setup Instructions

### Step 1: Create Google Cloud Project and Enable Gmail API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Navigate to **APIs & Services > Library**
4. Search for "Gmail API" and click on it
5. Click **Enable** to enable the Gmail API for your project

### Step 2: Create OAuth 2.0 Credentials

1. In the Google Cloud Console, go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. If prompted, configure the OAuth consent screen first:
   - Go to **APIs & Services > OAuth consent screen**
   - Choose **External** (unless you have a Google Workspace account)
   - Fill in the required fields:
     - App name: `Gmail Unsubscribe Tool` (or any name you prefer)
     - User support email: Your email address
     - Developer contact information: Your email address
   - Click **Save and Continue** through all steps
   - Add your Gmail address as a test user in the **Test users** section
4. Return to **Credentials** and click **Create Credentials > OAuth client ID**
5. Select **Desktop application** as the application type
6. Give it a name (e.g., "Gmail Unsubscribe Desktop Client")
7. Click **Create**
8. Download the JSON file by clicking the download button
9. Rename the downloaded file to `credentials.json` and place it in the same directory as `main.py`

### Step 3: Install Required Python Packages

```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests
```

### Step 4: Run the Tool

```bash
python main.py
```

On first run, the script will:
1. Open a browser window for authentication
2. Ask you to sign in to your Google account
3. Request permission to access your Gmail
4. Save the authentication token for future use

## Authentication Troubleshooting

### Common Issues and Solutions

**"Access blocked" error:**
- Click **Advanced** then **Go to app (unsafe)**
- This happens because the app is in testing mode

**"This app isn't verified" warning:**
- This is normal for personal projects
- Click **Advanced** and then **Go to Gmail Unsubscribe Tool (unsafe)**

**Token refresh failed:**
- Delete the `token.pickle` file and run the script again
- This will trigger a fresh authentication flow

**Not added as test user:**
- Go to **APIs & Services > OAuth consent screen > Test users**
- Add your Gmail address to the test users list

## File Structure

After setup, your directory should contain:
```
gmail-unsubscribe/
├── main.py                 # Main script
├── credentials.json        # OAuth client credentials (from Google Cloud Console)
├── token.pickle           # Saved authentication token (generated after first run)
└── README.md              # This file
```

## Usage

The script offers several modes:

1. **Dry Run Mode**: Preview what would happen without taking action
2. **Live Mode**: Actually perform unsubscribe requests
3. **Email Management**: Choose to keep, trash, or delete emails after unsubscribing
4. **Processing Methods**: Individual processing or group by sender (recommended)

## Security Notes

- Keep your `credentials.json` file secure and never commit it to version control
- The `token.pickle` file contains your access token - treat it as sensitive data
- The script only requests necessary Gmail permissions (read and modify)

## Useful Links

- [Google Cloud Console](https://console.cloud.google.com/)
- [Gmail API Documentation](https://developers.google.com/gmail/api)
- [OAuth 2.0 for Desktop Apps](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Google API Python Client](https://github.com/googleapis/google-api-python-client)

## Required Scopes

The script requests these Gmail API scopes:
- `https://www.googleapis.com/auth/gmail.readonly` - Read email messages
- `https://www.googleapis.com/auth/gmail.modify` - Add labels and move/delete messages

## Support

If you encounter issues with Google authentication, refer to:
- [Google OAuth 2.0 Troubleshooting](https://developers.google.com/identity/protocols/oauth2/troubleshooting)
- [Gmail API Error Codes](https://developers.google.com/gmail/api/guides/handle-errors)