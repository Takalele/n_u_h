import apprise
import os
from dotenv import load_dotenv

load_dotenv()

class AppriseNotifier:
    def __init__(self):
        # Read APPRISE_SERVICE_URL from environment variables
        self.apprise_service_url = os.getenv('APPRISE_SERVICE_URL')
        
        # Initialize apprise object
        self.apprise_obj = apprise.Apprise()
        
        # Add service URL
        if self.apprise_service_url:
            self.apprise_obj.add(self.apprise_service_url)

    def send_notification(self, title: str, body: str):
        if not self.apprise_service_url:
            # Skip sending
            return
        # Send the notification
        if not self.apprise_obj.notify(
            body=body,
            title=title,
        ):
            raise RuntimeError("Failed to send notification")
        
        print("Notification sent successfully")