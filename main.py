#!/usr/bin/env python3
"""
Gmail API Unsubscribe Script
Automatically finds and processes unsubscribe links from mailing lists
"""

import os
import re
import pickle
import base64
import requests
import json
import argparse
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Optional, Tuple
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 
          'https://www.googleapis.com/auth/gmail.modify']

class GmailUnsubscriber:
    def __init__(self, credentials_file='credentials.json', token_file='token.pickle', 
                 history_file='unsubscribe_history.json'):
        """
        Initialize Gmail API client
        
        Args:
            credentials_file: Path to OAuth2 credentials JSON file
            token_file: Path to store authentication tokens
            history_file: Path to store unsubscribe history
        """
        self.service = None
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.history_file = history_file
        self.unsubscribe_history = self.load_unsubscribe_history()
        self.last_api_call = 0  # Rate limiting
        self.authenticate()
    
    def authenticate(self):
        """Authenticate with Gmail API"""
        creds = None
        
        # Load existing token
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
        
        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"Token refresh failed: {e}")
                    print("Removing old token and re-authenticating...")
                    if os.path.exists(self.token_file):
                        os.remove(self.token_file)
                    creds = None
            
            if not creds:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Credentials file {self.credentials_file} not found.\n"
                        "Download it from Google Cloud Console:\n"
                        "1. Go to APIs & Services > Credentials\n"
                        "2. Create OAuth client ID > Desktop application\n"
                        "3. Download JSON file as 'credentials.json'"
                    )
                
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, SCOPES)
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    print(f"Authentication failed: {e}")
                    print("\nTroubleshooting:")
                    print("1. Check if you added yourself as a test user in Google Cloud Console")
                    print("2. Go to APIs & Services > OAuth consent screen > Test users")
                    print("3. Add your Gmail address to test users")
                    print("4. If you see 'Access blocked', click 'Advanced' then 'Go to app (unsafe)'")
                    raise
            
            # Save credentials for next run
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)
        
        self.service = build('gmail', 'v1', credentials=creds)
        print("✓ Authenticated with Gmail API")
    
    def load_unsubscribe_history(self) -> Dict:
        """Load unsubscribe history from JSON file"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load unsubscribe history from {self.history_file}: {e}")
                return {}
        return {}
    
    def save_unsubscribe_history(self):
        """Save unsubscribe history to JSON file"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.unsubscribe_history, f, indent=2, default=str)
        except IOError as e:
            print(f"Warning: Could not save unsubscribe history to {self.history_file}: {e}")
    
    def add_to_unsubscribe_history(self, sender_email: str, sender_name: str, 
                                  success: bool, unsubscribe_url: str = None):
        """Add a sender to the unsubscribe history"""
        sender_key = sender_email.lower().strip()
        self.unsubscribe_history[sender_key] = {
            'sender_name': sender_name,
            'sender_email': sender_email,
            'unsubscribe_attempted': True,
            'success': success,
            'timestamp': datetime.now().isoformat(),
            'unsubscribe_url': unsubscribe_url
        }
        self.save_unsubscribe_history()
    
    def is_already_unsubscribed(self, sender_email: str) -> bool:
        """Check if we've already attempted to unsubscribe from this sender"""
        sender_key = sender_email.lower().strip()
        return sender_key in self.unsubscribe_history
    
    def get_unsubscribe_record(self, sender_email: str) -> Optional[Dict]:
        """Get the unsubscribe record for a sender"""
        sender_key = sender_email.lower().strip()
        return self.unsubscribe_history.get(sender_key)
    
    def rate_limit_api_call(self, min_delay: float = 0.1):
        """Ensure minimum delay between API calls to prevent throttling"""
        current_time = time.time()
        time_since_last = current_time - self.last_api_call
        if time_since_last < min_delay:
            sleep_time = min_delay - time_since_last
            time.sleep(sleep_time)
        self.last_api_call = time.time()
    
    def search_emails(self, query: str, max_results: int = 100, inbox_only: bool = True) -> List[Dict]:
        """
        Search for emails matching the query
        
        Args:
            query: Gmail search query
            max_results: Maximum number of emails to return
            inbox_only: If True, search inbox-like locations including tabs (default: True)
            
        Returns:
            List of email message dictionaries
        """
        try:
            all_messages = []
            
            if inbox_only and "in:" not in query.lower():
                # Search across all inbox-like locations to match web UI behavior
                inbox_locations = ['in:inbox', 'in:primary', 'in:social', 'in:promotions', 'in:updates']
                
                print(f"🔍 Searching inbox categories for: '{query}'")
                print(f"📊 Max results per category: {max_results}")
                
                for location in inbox_locations:
                    location_query = f"{location} {query}"
                    print(f"  Searching {location}...")
                    
                    try:
                        results = self.service.users().messages().list(
                            userId='me', q=location_query, maxResults=max_results//len(inbox_locations) + 10).execute()
                        
                        messages = results.get('messages', [])
                        if messages:
                            print(f"    ✅ Found {len(messages)} emails in {location}")
                            all_messages.extend(messages)
                        else:
                            print(f"    📭 No emails in {location}")
                            
                    except Exception as e:
                        print(f"    ⚠️  Error searching {location}: {e}")
                
                # Remove duplicates based on message ID
                unique_messages = []
                seen_ids = set()
                for msg in all_messages:
                    if msg['id'] not in seen_ids:
                        unique_messages.append(msg)
                        seen_ids.add(msg['id'])
                
                messages = unique_messages[:max_results]
                print(f"Found {len(messages)} total unique emails across inbox categories")
                
            else:
                # Use original query as-is
                print(f"🔍 Searching with query: '{query}'")
                print(f"📊 Max results: {max_results}")
                
                results = self.service.users().messages().list(
                    userId='me', q=query, maxResults=max_results).execute()
                
                messages = results.get('messages', [])
                print(f"Found {len(messages)} emails matching query: {query}")
            
            return messages
            
        except Exception as e:
            print(f"Error searching emails: {e}")
            print(f"Exception details: {type(e).__name__}: {str(e)}")
            return []
    
    def get_message_details(self, message_id: str) -> Optional[Dict]:
        """Get full message details including headers and body"""
        try:
            self.rate_limit_api_call()
            message = self.service.users().messages().get(
                userId='me', id=message_id, format='full').execute()
            return message
        except Exception as e:
            print(f"Error getting message {message_id}: {e}")
            return None
    
    def extract_unsubscribe_links(self, message: Dict) -> List[str]:
        """
        Extract unsubscribe links from email headers and body
        
        Args:
            message: Gmail message object
            
        Returns:
            List of unsubscribe URLs
        """
        unsubscribe_links = []
        
        # Check List-Unsubscribe header
        headers = message.get('payload', {}).get('headers', [])
        for header in headers:
            if header['name'].lower() == 'list-unsubscribe':
                # Extract URLs from List-Unsubscribe header
                header_value = header['value']
                # Look for URLs in angle brackets
                urls = re.findall(r'<(https?://[^>]+)>', header_value)
                unsubscribe_links.extend(urls)
        
        # Extract from email body
        body_text = self.get_message_body(message)
        if body_text:
            # Common unsubscribe link patterns
            patterns = [
                r'https?://[^\s<>"]+unsubscribe[^\s<>"]*',
                r'https?://[^\s<>"]+opt[_-]?out[^\s<>"]*',
                r'https?://[^\s<>"]+remove[^\s<>"]*',
                r'href=["\']([^"\']*unsubscribe[^"\']*)["\']',
                r'href=["\']([^"\']*opt[_-]?out[^"\']*)["\']'
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, body_text, re.IGNORECASE)
                unsubscribe_links.extend(matches)
        
        # Remove duplicates and clean URLs
        unique_links = list(set(unsubscribe_links))
        cleaned_links = []
        
        for link in unique_links:
            # Clean up URLs
            link = link.strip('<>')
            if link.startswith('http'):
                cleaned_links.append(link)
        
        return cleaned_links
    
    def get_message_body(self, message: Dict) -> str:
        """Extract text content from email body"""
        payload = message.get('payload', {})
        body = ""
        
        def extract_text_from_part(part):
            nonlocal body
            if part.get('mimeType') == 'text/plain':
                data = part.get('body', {}).get('data')
                if data:
                    body += base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            elif part.get('mimeType') == 'text/html':
                data = part.get('body', {}).get('data')
                if data:
                    body += base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            
            # Handle multipart messages
            if 'parts' in part:
                for subpart in part['parts']:
                    extract_text_from_part(subpart)
        
        extract_text_from_part(payload)
        return body
    
    def get_sender_info(self, message: Dict) -> Tuple[str, str]:
        """Extract sender name and email from message"""
        headers = message.get('payload', {}).get('headers', [])
        sender_name = "Unknown"
        sender_email = "unknown@example.com"
        
        for header in headers:
            if header['name'].lower() == 'from':
                from_field = header['value']
                # Parse "Name <email@domain.com>" format
                match = re.match(r'(.*?)<([^>]+)>', from_field)
                if match:
                    sender_name = match.group(1).strip().strip('"')
                    sender_email = match.group(2).strip()
                else:
                    sender_email = from_field.strip()
                break
        
        return sender_name, sender_email
    
    def attempt_unsubscribe(self, url: str, sender_info: Tuple[str, str], max_retries: int = 2) -> bool:
        """
        Attempt to unsubscribe via HTTP request with retry logic
        
        Args:
            url: Unsubscribe URL
            sender_info: Tuple of (sender_name, sender_email)
            max_retries: Maximum number of retry attempts
            
        Returns:
            True if successful, False otherwise
        """
        sender_name, sender_email = sender_info
        
        for attempt in range(max_retries + 1):
            try:
                # Make GET request to unsubscribe URL
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Connection': 'close'  # Prevent connection pooling issues
                }
                
                if attempt == 0:
                    print(f"  Attempting unsubscribe from {sender_name} ({sender_email})")
                    print(f"  URL: {url}")
                else:
                    print(f"  Retry attempt {attempt}/{max_retries}")
                
                # Add small delay between retries
                if attempt > 0:
                    time.sleep(1 * attempt)
                
                response = requests.get(
                    url, 
                    headers=headers, 
                    timeout=15, 
                    allow_redirects=True,
                    stream=False  # Don't stream to avoid connection issues
                )
                
                if response.status_code == 200:
                    print(f"  ✓ Successfully accessed unsubscribe page")
                    response.close()  # Explicitly close the response
                    return True
                else:
                    print(f"  ✗ HTTP {response.status_code} - Failed to access unsubscribe page")
                    response.close()
                    if attempt < max_retries:
                        print(f"    Will retry...")
                    
            except requests.exceptions.Timeout as e:
                print(f"  ✗ Request timeout (attempt {attempt + 1}/{max_retries + 1}): {e}")
                if attempt == max_retries:
                    return False
            except requests.exceptions.ConnectionError as e:
                print(f"  ✗ Connection error (attempt {attempt + 1}/{max_retries + 1}): {e}")
                if attempt == max_retries:
                    return False
            except requests.exceptions.RequestException as e:
                print(f"  ✗ Request failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
                if attempt == max_retries:
                    return False
            except Exception as e:
                print(f"  ✗ Unexpected error (attempt {attempt + 1}/{max_retries + 1}): {e}")
                if attempt == max_retries:
                    return False
        
        return False
    
    def group_emails_by_sender(self, messages: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Group emails by sender to avoid processing duplicates
        
        Args:
            messages: List of Gmail message objects
            
        Returns:
            Dictionary mapping sender email to list of messages
        """
        sender_groups = {}
        
        print("Grouping emails by sender...")
        
        for i, msg in enumerate(messages, 1):
            print(f"  Processing email {i}/{len(messages)}...")
            message = self.get_message_details(msg['id'])
            if not message:
                print(f"    Failed to get message details for email {i}")
                continue
                
            sender_name, sender_email = self.get_sender_info(message)
            sender_key = sender_email.lower().strip()
            
            print(f"    Grouping email from: {sender_name} ({sender_email})")
            
            if sender_key not in sender_groups:
                sender_groups[sender_key] = {
                    'name': sender_name,
                    'email': sender_email,
                    'messages': []
                }
                print(f"    Created new group for sender: {sender_email}")
            else:
                print(f"    Added to existing group for: {sender_email} (total: {len(sender_groups[sender_key]['messages']) + 1} emails)")
            
            sender_groups[sender_key]['messages'].append(message)
        
        # Sort by number of emails (most emails first)
        sorted_senders = dict(sorted(sender_groups.items(), 
                                   key=lambda x: len(x[1]['messages']), 
                                   reverse=True))
        
        print(f"Found {len(sorted_senders)} unique senders")
        
        # Show top senders
        print("\nTop senders by email count:")
        for i, (sender_key, data) in enumerate(list(sorted_senders.items())[:10], 1):
            count = len(data['messages'])
            print(f"  {i}. {data['name']} ({sender_key}): {count} emails")
        
        return sorted_senders
    
    def label_message(self, message_id: str, label_name: str = "Unsubscribed"):
        """Add a label to mark processed messages"""
        try:
            # Create label if it doesn't exist
            labels = self.service.users().labels().list(userId='me').execute()
            label_id = None
            
            for label in labels.get('labels', []):
                if label['name'] == label_name:
                    label_id = label['id']
                    break
            
            if not label_id:
                # Create new label
                label_object = {
                    'name': label_name,
                    'messageListVisibility': 'show',
                    'labelListVisibility': 'labelShow'
                }
                created_label = self.service.users().labels().create(
                    userId='me', body=label_object).execute()
                label_id = created_label['id']
            
            # Add label to message
            self.service.users().messages().modify(
                userId='me', id=message_id,
                body={'addLabelIds': [label_id]}
            ).execute()
            
        except Exception as e:
            print(f"  Warning: Could not add label - {e}")
    
    def delete_messages(self, message_ids: List[str], sender_name: str) -> int:
        """
        Delete multiple messages by ID
        
        Args:
            message_ids: List of Gmail message IDs to delete
            sender_name: Name of sender (for logging)
            
        Returns:
            Number of successfully deleted messages
        """
        if not message_ids:
            return 0
            
        deleted_count = 0
        
        try:
            # Gmail API allows batch deletion, but we'll do it one by one for better error handling
            print(f"  Deleting {len(message_ids)} emails from {sender_name}...")
            
            for i, message_id in enumerate(message_ids, 1):
                try:
                    self.rate_limit_api_call()
                    self.service.users().messages().delete(userId='me', id=message_id).execute()
                    deleted_count += 1
                    
                    # Show progress for large batches
                    if len(message_ids) > 5 and i % 5 == 0:
                        print(f"    Deleted {i}/{len(message_ids)} emails...")
                        
                except Exception as e:
                    print(f"    Warning: Could not delete message {i} - {e}")
            
            print(f"  ✓ Successfully deleted {deleted_count}/{len(message_ids)} emails")
            
        except Exception as e:
            print(f"  ✗ Error during batch deletion: {e}")
        
        return deleted_count

    def move_to_trash(self, message_ids: List[str], sender_name: str) -> int:
        """
        Move multiple messages to trash (safer than permanent delete)
        
        Args:
            message_ids: List of Gmail message IDs to trash
            sender_name: Name of sender (for logging)
            
        Returns:
            Number of successfully trashed messages
        """
        if not message_ids:
            return 0
            
        trashed_count = 0
        
        try:
            print(f"  Moving {len(message_ids)} emails from {sender_name} to trash...")
            
            for i, message_id in enumerate(message_ids, 1):
                try:
                    self.rate_limit_api_call()
                    self.service.users().messages().trash(userId='me', id=message_id).execute()
                    trashed_count += 1
                    
                    # Show progress for large batches
                    if len(message_ids) > 5 and i % 5 == 0:
                        print(f"    Moved {i}/{len(message_ids)} emails to trash...")
                        
                except Exception as e:
                    print(f"    Warning: Could not trash message {i} - {e}")
            
            print(f"  ✓ Successfully moved {trashed_count}/{len(message_ids)} emails to trash")
            
        except Exception as e:
            print(f"  ✗ Error during batch trash operation: {e}")
        
        return trashed_count
    
    def process_unsubscribes(self, search_query: str = "unsubscribe", 
                           max_emails: int = 50, dry_run: bool = True,
                           delete_after_unsubscribe: bool = False,
                           permanent_delete: bool = False,
                           inbox_only: bool = True,
                           delete_without_unsubscribe: bool = True):
        """
        Main method to find and process unsubscribe requests
        
        Args:
            search_query: Gmail search query to find emails
            max_emails: Maximum number of emails to process
            dry_run: If True, only show what would be done without taking action
            delete_after_unsubscribe: If True, delete emails after successful unsubscribe
            permanent_delete: If True, permanently delete (vs move to trash)
            inbox_only: If True, search only in inbox (default: True)
            delete_without_unsubscribe: If True, delete emails even when no unsubscribe link is found
        """
        print(f"\n{'='*60}")
        print(f"Gmail Unsubscribe Tool - {'DRY RUN' if dry_run else 'LIVE RUN'}")
        print(f"{'='*60}")
        
        # Search for emails containing unsubscribe links
        messages = self.search_emails(search_query, max_emails, inbox_only)
        
        if not messages:
            print("No messages found matching the search criteria.")
            return
        
        processed_count = 0
        success_count = 0
        skipped_count = 0
        
        # Track processed senders to avoid duplicates
        processed_senders = set()
        sender_details = {}  # Store details for summary
        
        for i, msg in enumerate(messages, 1):
            print(f"\nProcessing email {i}/{len(messages)}...")
            
            # Get full message details
            message = self.get_message_details(msg['id'])
            if not message:
                continue
            
            # Get sender information
            sender_name, sender_email = self.get_sender_info(message)
            
            # Check if we've already processed this sender
            sender_key = sender_email.lower().strip()
            if sender_key in processed_senders:
                print(f"  ⏭️  Skipping {sender_name} - already processed this sender")
                
                if delete_after_unsubscribe and not dry_run:
                    # Move email to trash since sender was already processed
                    if permanent_delete:
                        self.delete_messages([msg['id']], sender_name)
                    else:
                        self.move_to_trash([msg['id']], sender_name)
                elif dry_run and delete_after_unsubscribe:
                    action = "permanently delete" if permanent_delete else "move to trash"
                    print(f"  [DRY RUN] Would {action} this email from previously processed sender")
                
                skipped_count += 1
                continue
            
            # Extract unsubscribe links
            unsubscribe_links = self.extract_unsubscribe_links(message)
            
            if not unsubscribe_links:
                print(f"  No unsubscribe links found for {sender_name}")
                
                # If delete_without_unsubscribe is True and delete_after_unsubscribe is True, delete anyway
                if delete_without_unsubscribe and delete_after_unsubscribe and not dry_run:
                    print(f"  Deleting email without unsubscribe attempt...")
                    if permanent_delete:
                        self.delete_messages([msg['id']], sender_name)
                    else:
                        self.move_to_trash([msg['id']], sender_name)
                elif dry_run and delete_without_unsubscribe and delete_after_unsubscribe:
                    action = "permanently delete" if permanent_delete else "move to trash"
                    print(f"  [DRY RUN] Would {action} email without unsubscribe attempt")
                
                continue
            
            print(f"  Found {len(unsubscribe_links)} unsubscribe link(s) for {sender_name}")
            
            # Add sender to processed set
            processed_senders.add(sender_key)
            sender_details[sender_key] = {
                'name': sender_name,
                'email': sender_email,
                'links': unsubscribe_links,
                'success': False
            }
            
            if dry_run:
                print(f"  [DRY RUN] Would attempt to unsubscribe from {sender_email}")
                for j, link in enumerate(unsubscribe_links, 1):
                    print(f"    Link {j}: {link}")
                sender_details[sender_key]['success'] = True  # Assume success for dry run
            else:
                # Attempt to unsubscribe using the first link
                success = self.attempt_unsubscribe(unsubscribe_links[0], (sender_name, sender_email))
                sender_details[sender_key]['success'] = success
                
                if success:
                    success_count += 1
                
                # Delete or trash the email regardless of unsubscribe success
                if delete_after_unsubscribe:
                    if permanent_delete:
                        self.delete_messages([msg['id']], sender_name)
                    else:
                        self.move_to_trash([msg['id']], sender_name)
                else:
                    # Only label if unsubscribe was successful
                    if success:
                        self.label_message(msg['id'])
            
            processed_count += 1
        
        # Print detailed summary
        print(f"\n{'='*60}")
        print(f"DETAILED SUMMARY:")
        print(f"{'='*60}")
        print(f"  Total emails scanned: {len(messages)}")
        print(f"  Unique senders processed: {processed_count}")
        print(f"  Duplicate senders skipped: {skipped_count}")
        
        if not dry_run:
            print(f"  Successful unsubscribes: {success_count}")
            print(f"  Failed unsubscribes: {processed_count - success_count}")
        
        # List all processed senders
        if sender_details:
            print(f"\nProcessed Senders:")
            for sender_key, details in sender_details.items():
                status = "✓" if details['success'] else "✗"
                mode = "[DRY RUN]" if dry_run else ""
                print(f"  {status} {details['name']} ({details['email']}) {mode}")
        
        print(f"{'='*60}")

    def process_unsubscribes_by_sender(self, search_query: str = "unsubscribe", 
                                     max_emails: int = 50, dry_run: bool = True,
                                     delete_after_unsubscribe: bool = False,
                                     permanent_delete: bool = False,
                                     inbox_only: bool = True,
                                     delete_without_unsubscribe: bool = True):
        """
        Process unsubscribes grouped by sender (more efficient)
        
        Args:
            search_query: Gmail search query to find emails
            max_emails: Maximum number of emails to process
            dry_run: If True, only show what would be done without taking action
            delete_after_unsubscribe: If True, delete emails after successful unsubscribe
            permanent_delete: If True, permanently delete (vs move to trash)
            inbox_only: If True, search only in inbox (default: True)
            delete_without_unsubscribe: If True, delete emails even when no unsubscribe link is found
        """
        print(f"\n{'='*60}")
        action_mode = "DRY RUN" if dry_run else "LIVE RUN"
        delete_mode = ""
        if delete_after_unsubscribe and not dry_run:
            delete_mode = " + DELETE" if permanent_delete else " + TRASH"
        print(f"Gmail Unsubscribe Tool (Grouped by Sender) - {action_mode}{delete_mode}")
        print(f"{'='*60}")
        
        # Search for emails containing unsubscribe links
        messages = self.search_emails(search_query, max_emails, inbox_only)
        
        if not messages:
            print("No messages found matching the search criteria.")
            return
        
        # Group emails by sender
        sender_groups = self.group_emails_by_sender(messages)
        
        processed_count = 0
        success_count = 0
        total_emails_affected = 0
        total_deleted = 0
        
        for sender_key, sender_data in sender_groups.items():
            sender_name = sender_data['name']
            sender_email = sender_data['email']
            messages_from_sender = sender_data['messages']
            
            processed_count += 1
            email_count = len(messages_from_sender)
            total_emails_affected += email_count
            
            print(f"\nProcessing sender {processed_count}/{len(sender_groups)}: {sender_name}")
            print(f"  Email count: {email_count}")
            
            # Check if we've already attempted to unsubscribe from this sender
            if self.is_already_unsubscribed(sender_email):
                unsubscribe_record = self.get_unsubscribe_record(sender_email)
                print(f"  📝 Previously attempted unsubscribe on {unsubscribe_record['timestamp'][:10]}")
                print(f"     Status: {'Success' if unsubscribe_record['success'] else 'Failed'}")
                
                if delete_after_unsubscribe and not dry_run:
                    # Skip unsubscribe attempt, just delete/trash the emails
                    message_ids = [msg['id'] for msg in messages_from_sender]
                    print(f"  🗑️  Skipping unsubscribe (already attempted), proceeding to delete emails...")
                    
                    if permanent_delete:
                        deleted_count = self.delete_messages(message_ids, sender_name)
                    else:
                        deleted_count = self.move_to_trash(message_ids, sender_name)
                    
                    total_deleted += deleted_count
                elif dry_run:
                    print(f"  [DRY RUN] Would skip unsubscribe (already attempted)")
                    if delete_after_unsubscribe:
                        action = "permanently delete" if permanent_delete else "move to trash"
                        print(f"  [DRY RUN] Would {action} {email_count} emails without re-attempting unsubscribe")
                else:
                    print(f"  ⏭️  Skipping (already attempted unsubscribe, no deletion requested)")
                
                continue
            
            # Use the most recent email to find unsubscribe links
            latest_message = messages_from_sender[0]  # They're already sorted by recency in Gmail API
            unsubscribe_links = self.extract_unsubscribe_links(latest_message)
            
            if not unsubscribe_links:
                print(f"  No unsubscribe links found for {sender_name}")
                
                # If delete_without_unsubscribe is True and delete_after_unsubscribe is True, delete anyway
                if delete_without_unsubscribe and delete_after_unsubscribe and not dry_run:
                    print(f"  Deleting {email_count} emails without unsubscribe attempt...")
                    message_ids = [msg['id'] for msg in messages_from_sender]
                    if permanent_delete:
                        deleted_count = self.delete_messages(message_ids, sender_name)
                    else:
                        deleted_count = self.move_to_trash(message_ids, sender_name)
                    total_deleted += deleted_count
                elif dry_run and delete_without_unsubscribe and delete_after_unsubscribe:
                    action = "permanently delete" if permanent_delete else "move to trash"
                    print(f"  [DRY RUN] Would {action} {email_count} emails without unsubscribe attempt")
                
                continue
            
            print(f"  Found {len(unsubscribe_links)} unsubscribe link(s)")
            
            if dry_run:
                print(f"  [DRY RUN] Would attempt to unsubscribe from {sender_email}")
                print(f"  [DRY RUN] This would affect {email_count} emails from this sender")
                if delete_after_unsubscribe:
                    action = "permanently delete" if permanent_delete else "move to trash"
                    print(f"  [DRY RUN] Would {action} {email_count} emails after unsubscribe")
                for j, link in enumerate(unsubscribe_links, 1):
                    print(f"    Link {j}: {link}")
            else:
                # Attempt to unsubscribe using the first link
                success = self.attempt_unsubscribe(unsubscribe_links[0], (sender_name, sender_email))
                
                # Record the unsubscribe attempt in history
                self.add_to_unsubscribe_history(sender_email, sender_name, success, unsubscribe_links[0])
                print(f"  📝 Recorded unsubscribe attempt in history")
                
                if success:
                    success_count += 1
                else:
                    print(f"  Failed to unsubscribe from {sender_name}")
                
                # Get message IDs for deletion/labeling
                message_ids = [msg['id'] for msg in messages_from_sender]
                
                if delete_after_unsubscribe:
                    # Delete or trash emails regardless of unsubscribe success
                    if permanent_delete:
                        deleted_count = self.delete_messages(message_ids, sender_name)
                    else:
                        deleted_count = self.move_to_trash(message_ids, sender_name)
                    
                    total_deleted += deleted_count
                else:
                    # Only label if unsubscribe was successful
                    if success:
                        print(f"  Labeling {email_count} emails from this sender...")
                        for message in messages_from_sender:
                            self.label_message(message['id'])
        
        # Print detailed summary
        print(f"\n{'='*60}")
        print(f"SUMMARY (Grouped by Sender):")
        print(f"{'='*60}")
        print(f"  Total emails scanned: {len(messages)}")
        print(f"  Unique senders found: {len(sender_groups)}")
        print(f"  Senders processed: {processed_count}")
        print(f"  Total emails affected: {total_emails_affected}")
        print(f"  Total emails deleted/trash: {total_deleted}")
        
        if not dry_run:
            print(f"  Successful unsubscribes: {success_count}")
            print(f"  Failed unsubscribes: {processed_count - success_count}")
            
            if delete_after_unsubscribe:
                action = "deleted" if permanent_delete else "moved to trash"
                print(f"  Emails {action}: {total_deleted}")
                print(f"  Estimated inbox cleanup: {total_deleted} emails removed")
            else:
                print(f"  Emails labeled: {success_count * (total_emails_affected / len(sender_groups)) if sender_groups else 0:.0f}")
        
        print(f"{'='*60}")


def setup_argument_parser():
    """Set up command-line argument parser"""
    parser = argparse.ArgumentParser(
        description='Gmail Unsubscribe Tool - Automatically find and process unsubscribe links',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (default)
  python main.py
  
  # Dry run with default settings
  python main.py --dry-run
  
  # Live run: unsubscribe + trash emails, search newsletters, max 100 emails
  python main.py --live --trash --query newsletter --max-emails 100
  
  # Live run: unsubscribe + permanently delete, group by sender
  python main.py --live --delete --method 2 --query promotional
  
  # Dry run: preview what would happen with custom query
  python main.py --dry-run --query "unsubscribe OR newsletter" --max-emails 50
        """)
    
    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--dry-run', '--preview', action='store_true', 
                           help='Preview what would be done without taking action (default)')
    mode_group.add_argument('--live', action='store_true',
                           help='Actually perform unsubscribe and deletion actions')
    
    # Search options
    query_group = parser.add_mutually_exclusive_group()
    query_group.add_argument('--query', '-q', type=str, default='unsubscribe',
                            choices=['unsubscribe', 'newsletter', 'promotional', 'list-unsubscribe'],
                            help='Predefined Gmail search query (default: unsubscribe)')
    query_group.add_argument('--custom-query', type=str, 
                            help='Custom Gmail search query (overrides --query)')
    parser.add_argument('--max-emails', '-m', type=int, default=100,
                       help='Maximum number of emails to process (default: 100)')
    
    # Processing method
    parser.add_argument('--method', type=int, choices=[1, 2], default=2,
                       help='Processing method: 1=individual emails, 2=group by sender (default: 2)')
    
    # Deletion options
    deletion_group = parser.add_mutually_exclusive_group()
    deletion_group.add_argument('--keep', action='store_true', 
                               help='Keep emails and add "Unsubscribed" label (default)')
    deletion_group.add_argument('--trash', action='store_true',
                               help='Move emails to trash after unsubscribe attempt')
    deletion_group.add_argument('--delete', action='store_true',
                               help='Permanently delete emails after unsubscribe attempt')
    
    # Search scope
    parser.add_argument('--all-folders', action='store_true',
                       help='Search all folders (default: inbox only)')
    
    # Delete without unsubscribe option
    parser.add_argument('--delete-without-unsubscribe', action='store_true', default=True,
                       help='Delete/trash emails even when no unsubscribe link is found (default: True)')
    parser.add_argument('--no-delete-without-unsubscribe', action='store_false', dest='delete_without_unsubscribe',
                       help='Only delete/trash emails that have unsubscribe links')
    
    # Non-interactive mode
    parser.add_argument('--yes', '-y', action='store_true',
                       help='Answer yes to all prompts (non-interactive mode)')
    
    # Verbose output
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose output')
    
    return parser


def main():
    """Main function with command-line argument support"""
    parser = setup_argument_parser()
    args = parser.parse_args()
    
    try:
        # Initialize the unsubscriber
        unsubscriber = GmailUnsubscriber()
        
        # Determine run mode
        if args.live:
            dry_run = False
        else:
            dry_run = True  # Default to dry run if neither --live nor --dry-run specified
        
        # Determine search query
        if args.custom_query:
            search_query = args.custom_query
        else:
            search_query = args.query
        
        # Determine deletion behavior
        delete_after_unsubscribe = False
        permanent_delete = False
        
        if args.trash:
            delete_after_unsubscribe = True
            permanent_delete = False
        elif args.delete:
            delete_after_unsubscribe = True
            permanent_delete = True
        # Default is keep (args.keep or none specified)
        
        # Determine search scope
        inbox_only = not args.all_folders
        
        # If not in non-interactive mode and doing a live run, ask for confirmation
        if not dry_run and not args.yes:
            if delete_after_unsubscribe:
                action = "permanently delete" if permanent_delete else "move to trash"
                print(f"⚠️  This will attempt to unsubscribe AND {action} emails.")
            else:
                print("⚠️  This will attempt to unsubscribe from mailing lists.")
            
            confirm = input("Continue? (yes/no): ")
            if confirm.lower() != 'yes':
                print("Cancelled.")
                return
        
        # Print configuration summary
        print(f"\nGmail Unsubscribe Tool")
        print("=" * 40)
        print(f"Mode: {'LIVE RUN' if not dry_run else 'DRY RUN'}")
        print(f"Search query: {search_query}")
        print(f"Max emails: {args.max_emails}")
        print(f"Processing method: {'Individual emails' if args.method == 1 else 'Group by sender'}")
        print(f"Search scope: {'All folders' if not inbox_only else 'Inbox only'}")
        
        if delete_after_unsubscribe:
            action = "Permanently delete" if permanent_delete else "Move to trash"
            print(f"After unsubscribe: {action} emails")
        else:
            print("After unsubscribe: Keep emails and add label")
        
        if args.verbose:
            print(f"Verbose mode: Enabled")
        
        print("=" * 40)
        
        # Process unsubscribes using chosen method
        if args.method == 1:
            unsubscriber.process_unsubscribes(
                search_query=search_query,
                max_emails=args.max_emails,
                dry_run=dry_run,
                delete_after_unsubscribe=delete_after_unsubscribe,
                permanent_delete=permanent_delete,
                inbox_only=inbox_only,
                delete_without_unsubscribe=args.delete_without_unsubscribe
            )
        else:
            unsubscriber.process_unsubscribes_by_sender(
                search_query=search_query,
                max_emails=args.max_emails,
                dry_run=dry_run,
                delete_after_unsubscribe=delete_after_unsubscribe,
                permanent_delete=permanent_delete,
                inbox_only=inbox_only,
                delete_without_unsubscribe=args.delete_without_unsubscribe
            )
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
