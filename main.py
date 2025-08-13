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
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 
          'https://www.googleapis.com/auth/gmail.modify']

class GmailUnsubscriber:
    def __init__(self, credentials_file='credentials.json', token_file='token.pickle'):
        """
        Initialize Gmail API client
        
        Args:
            credentials_file: Path to OAuth2 credentials JSON file
            token_file: Path to store authentication tokens
        """
        self.service = None
        self.credentials_file = credentials_file
        self.token_file = token_file
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
    
    def search_emails(self, query: str, max_results: int = 100) -> List[Dict]:
        """
        Search for emails matching the query
        
        Args:
            query: Gmail search query
            max_results: Maximum number of emails to return
            
        Returns:
            List of email message dictionaries
        """
        try:
            results = self.service.users().messages().list(
                userId='me', q=query, maxResults=max_results).execute()
            
            messages = results.get('messages', [])
            print(f"Found {len(messages)} emails matching query: {query}")
            return messages
            
        except Exception as e:
            print(f"Error searching emails: {e}")
            return []
    
    def get_message_details(self, message_id: str) -> Optional[Dict]:
        """Get full message details including headers and body"""
        try:
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
    
    def attempt_unsubscribe(self, url: str, sender_info: Tuple[str, str]) -> bool:
        """
        Attempt to unsubscribe via HTTP request
        
        Args:
            url: Unsubscribe URL
            sender_info: Tuple of (sender_name, sender_email)
            
        Returns:
            True if successful, False otherwise
        """
        sender_name, sender_email = sender_info
        
        try:
            # Make GET request to unsubscribe URL
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            print(f"  Attempting unsubscribe from {sender_name} ({sender_email})")
            print(f"  URL: {url}")
            
            response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
            
            if response.status_code == 200:
                print(f"  ✓ Successfully accessed unsubscribe page")
                return True
            else:
                print(f"  ✗ HTTP {response.status_code} - Failed to access unsubscribe page")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"  ✗ Request failed: {e}")
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
        
        for msg in messages:
            message = self.get_message_details(msg['id'])
            if not message:
                continue
                
            sender_name, sender_email = self.get_sender_info(message)
            sender_key = sender_email.lower().strip()
            
            if sender_key not in sender_groups:
                sender_groups[sender_key] = {
                    'name': sender_name,
                    'email': sender_email,
                    'messages': []
                }
            
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
                           max_emails: int = 50, dry_run: bool = True):
        """
        Main method to find and process unsubscribe requests
        
        Args:
            search_query: Gmail search query to find emails
            max_emails: Maximum number of emails to process
            dry_run: If True, only show what would be done without taking action
        """
        print(f"\n{'='*60}")
        print(f"Gmail Unsubscribe Tool - {'DRY RUN' if dry_run else 'LIVE RUN'}")
    def process_unsubscribes_by_sender(self, search_query: str = "unsubscribe", 
                                     max_emails: int = 50, dry_run: bool = True,
                                     delete_after_unsubscribe: bool = False,
                                     permanent_delete: bool = False):
        """
        Process unsubscribes grouped by sender (more efficient)
        
        Args:
            search_query: Gmail search query to find emails
            max_emails: Maximum number of emails to process
            dry_run: If True, only show what would be done without taking action
            delete_after_unsubscribe: If True, delete emails after successful unsubscribe
            permanent_delete: If True, permanently delete (vs move to trash)
        """
        print(f"\n{'='*60}")
        action_mode = "DRY RUN" if dry_run else "LIVE RUN"
        delete_mode = ""
        if delete_after_unsubscribe and not dry_run:
            delete_mode = " + DELETE" if permanent_delete else " + TRASH"
        print(f"Gmail Unsubscribe Tool (Grouped by Sender) - {action_mode}{delete_mode}")
        print(f"{'='*60}")
        
        # Search for emails containing unsubscribe links
        messages = self.search_emails(search_query, max_emails)
        
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
            
            # Use the most recent email to find unsubscribe links
            latest_message = messages_from_sender[0]  # They're already sorted by recency in Gmail API
            unsubscribe_links = self.extract_unsubscribe_links(latest_message)
            
            if not unsubscribe_links:
                print(f"  No unsubscribe links found for {sender_name}")
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
                
                if success:
                    success_count += 1
                    
                    # Get message IDs for deletion/labeling
                    message_ids = [msg['id'] for msg in messages_from_sender]
                    
                    if delete_after_unsubscribe:
                        # Delete or trash emails
                        if permanent_delete:
                            deleted_count = self.delete_messages(message_ids, sender_name)
                        else:
                            deleted_count = self.move_to_trash(message_ids, sender_name)
                        
                        total_deleted += deleted_count
                    else:
                        # Label all messages from this sender
                        print(f"  Labeling {email_count} emails from this sender...")
                        for message in messages_from_sender:
                            self.label_message(message['id'])
                else:
                    print(f"  Failed to unsubscribe from {sender_name}")
        
        # Print detailed summary
        print(f"\n{'='*60}")
        print(f"SUMMARY (Grouped by Sender):")
        print(f"{'='*60}")
        print(f"  Total emails scanned: {len(messages)}")
        print(f"  Unique senders found: {len(sender_groups)}")
        print(f"  Senders processed: {processed_count}")
        print(f"  Total emails affected: {total_emails_affected}")
        
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
        
        # Search for emails containing unsubscribe links
        messages = self.search_emails(search_query, max_emails)
        
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
                skipped_count += 1
                continue
            
            # Extract unsubscribe links
            unsubscribe_links = self.extract_unsubscribe_links(message)
            
            if not unsubscribe_links:
                print(f"  No unsubscribe links found for {sender_name}")
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
                    # Label the message as processed
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


def main():
    """Main function with example usage"""
    try:
        # Initialize the unsubscriber
        unsubscriber = GmailUnsubscriber()
        
        # Example searches - customize these based on your needs
        search_queries = [
            "unsubscribe",  # General search for emails with unsubscribe
            "newsletter",   # Newsletter emails
            "promotional",  # Promotional emails
            "list-unsubscribe", # Emails with List-Unsubscribe header
        ]
        
        print("Gmail Unsubscribe Tool")
        print("=" * 40)
        
        # Ask user which mode to run in
        print("\nSelect mode:")
        print("1. Dry run (preview only)")
        print("2. Live run (actually unsubscribe)")
        choice = input("Enter choice (1 or 2): ").strip()
        
        dry_run = choice != "2"
        
        if dry_run:
            print("\n⚠️  Running in DRY RUN mode - no actual unsubscriptions will be performed")
        else:
            confirm = input("\n⚠️  This will attempt to unsubscribe from mailing lists. Continue? (yes/no): ")
            if confirm.lower() != 'yes':
                print("Cancelled.")
                return
        
        # Ask about deletion
        delete_after_unsubscribe = False
        permanent_delete = False
        
        if not dry_run:
            print("\nWhat to do with emails after successful unsubscribe:")
            print("1. Keep emails and add 'Unsubscribed' label (default)")
            print("2. Move emails to trash (recoverable)")
            print("3. Permanently delete emails (not recoverable)")
            
            delete_choice = input("Enter choice (1-3, default 1): ").strip() or "1"
            
            if delete_choice == "2":
                delete_after_unsubscribe = True
                permanent_delete = False
                confirm_delete = input("⚠️  This will move emails to trash after unsubscribing. Continue? (yes/no): ")
                if confirm_delete.lower() != 'yes':
                    print("Cancelled.")
                    return
            elif delete_choice == "3":
                delete_after_unsubscribe = True
                permanent_delete = True
                confirm_delete = input("⚠️  This will PERMANENTLY DELETE emails after unsubscribing. This cannot be undone! Continue? (yes/no): ")
                if confirm_delete.lower() != 'yes':
                    print("Cancelled.")
                    return
        else:
            # For dry run, ask what they want to preview
            print("\nDry run options:")
            print("1. Preview unsubscribe + keep emails")
            print("2. Preview unsubscribe + trash emails")
            print("3. Preview unsubscribe + delete emails")
            
            delete_choice = input("Enter choice (1-3, default 1): ").strip() or "1"
            if delete_choice == "2":
                delete_after_unsubscribe = True
                permanent_delete = False
            elif delete_choice == "3":
                delete_after_unsubscribe = True
                permanent_delete = True
        
        # Let user choose processing method
        print("\nSelect processing method:")
        print("1. Process each email individually")
        print("2. Group by sender (recommended - avoids duplicates)")
        method_choice = input("Enter choice (1 or 2, default 2): ").strip() or "2"
        
        # Let user choose search query
        print("\nSelect search query:")
        for i, query in enumerate(search_queries, 1):
            print(f"{i}. {query}")
        print("5. Custom query")
        
        query_choice = input("Enter choice (1-5): ").strip()
        
        if query_choice == "5":
            search_query = input("Enter custom Gmail search query: ").strip()
        else:
            try:
                search_query = search_queries[int(query_choice) - 1]
            except (ValueError, IndexError):
                search_query = "unsubscribe"
        
        # Get number of emails to process
        try:
            max_emails = int(input("Maximum emails to process (default 100): ") or "100")
        except ValueError:
            max_emails = 100
        
        # Process unsubscribes using chosen method
        if method_choice == "1":
            unsubscriber.process_unsubscribes(
                search_query=search_query,
                max_emails=max_emails,
                dry_run=dry_run,
                delete_after_unsubscribe=delete_after_unsubscribe,
                permanent_delete=permanent_delete
            )
        else:
            unsubscriber.process_unsubscribes_by_sender(
                search_query=search_query,
                max_emails=max_emails,
                dry_run=dry_run,
                delete_after_unsubscribe=delete_after_unsubscribe,
                permanent_delete=permanent_delete
            )
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
