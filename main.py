import imaplib
import email
import time
import sys
import logging
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from apprise_notifier import AppriseNotifier
from dotenv import load_dotenv
import os

load_dotenv()

# Constants
# Used as search criteria for netflix mail and button to click. Could be changed by Netflix in the future
SENDER_EMAILS = ['info@account.netflix.com']
NETFLIX_LINK_START = ['www.netflix.com/account/update-primary', 'www.netflix.com/account/set-primary']
BUTTON_SEARCH_ATTR_NAME = 'data-uia'
BUTTON_SEARCH_ATTR_VALUE = 'set-primary-location-action'


class NetflixLocationUpdate:
    _mail: imaplib.IMAP4_SSL
    _mailbox_name: str              # Mailbox name for incoming Emails (normally INBOX)
    _move_to_mailbox: str           # If true, Netflix Emails will be moved into another mailbox
    _move_to_mailbox_name: str      # Mailbox Name where the Netflix Emails shall be moved

    def __init__(self):
        self._mailbox_name = os.getenv('EMAIL', 'INBOX')
        self._move_to_mailbox = os.getenv('MOVE_TO_MAILBOX_TO', "False").lower() in ["1", "t", "true"]
        self._move_to_mailbox_name = os.getenv('MAILBOX_TO', 'Netflix')

        # Email config
        imap_server = os.getenv('IMAP_SERVER')
        imap_port = int(os.getenv('IMAP_PORT', '993')) ##int
        imap_username = os.getenv('IMAP_USERNAME')
        imap_password = os.getenv('IMAP_PASSWORD')

        # Logging config
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )
        logging.info('---------------- Script started ----------------\n')

        self._mail = self.__init_mails(imap_server, imap_port, imap_username, imap_password)

        # Create the Netflix folder in the mail account
        if self._move_to_mailbox:
            self._mail.create(self._move_to_mailbox_name)

    def __del__(self):
        self.close()

    def init_webdriver(self) -> webdriver.Firefox:
        options = Options()
        if os.getenv("HEADLESS", "True").lower() in ["1", "t", "true"]:
            options.add_argument("-headless")
        driver = webdriver.Firefox(options=options)
        return driver

    @staticmethod
    def __init_mails(imap_server: str, imap_port: int, username: str, password: str) -> imaplib.IMAP4_SSL:
        # Connect to the IMAP server
        logging.info(f"Login {username} to {imap_server}:{imap_port}\n")
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(username, password)
        return mail

    def close(self):
        # Close the mail connection
        if self._mail is not None:
            self._mail.close()
            self._mail.logout()
        logging.info('---------------- Script shutdown ----------------\n')

    def netflix_login(self, driver: webdriver.Firefox):
        try:
            email_field = driver.find_element(By.CSS_SELECTOR, 'input[name="userLoginId"]')
            password_field = driver.find_element(By.CSS_SELECTOR, 'input[name="password"]')
            email_field.send_keys(os.getenv('NETFLIX_USERNAME'))
            password_field.send_keys(os.getenv('NETFLIX_PASSWORD'))
            login_button = driver.find_element(By.CSS_SELECTOR, 'button[data-uia=login-submit-button]')
            login_button.send_keys(Keys.RETURN)
            time.sleep(1)
            return True
        except Exception as e:
            logging.error(e)
            return False

    def parse_html_for_button(self, update_link: str) -> bool:
        driver = self.init_webdriver()
        try:
            driver.get(update_link)
            time.sleep(1)
            try:
                email_field = driver.find_element(By.CSS_SELECTOR, 'input[name="userLoginId"]')
                logging.info('Currently not logged in. Try to login to Netflix account')
                self.netflix_login(driver)
            except Exception as e:
                logging.info('Already logged in.')
                pass

            try:
                # Find the confirmation button after login
                button = driver.find_element(By.CSS_SELECTOR, f'button[{BUTTON_SEARCH_ATTR_NAME}={BUTTON_SEARCH_ATTR_VALUE}]')
                # Just press all buttons, found in the HTML page. This is done to ensure, that the correct button got pressed
                if button is not None:
                    button.click()
                    AppriseNotifier().send_notification("Netflix", "Household got updated!")
                    return True
            except Exception as e:
                logging.error(e)
                pass
        finally:
            driver.quit()
        return False

    def fetch_mails(self):
        # Select the mailbox you want to fetch emails from
        self._mail.select(self._mailbox_name)

        logging.info(f"Fetching Mails")

        # Search for unread emails from the specified sender
        search_criteria = f'(UNSEEN FROM "Netflix")'
        result, data = self._mail.search(None, search_criteria)

        # Get the list of email IDs
        email_ids = data[0].split()

        # List to store extracted href attributes
        href_list = []

        # Iterate over the email IDs in reverse order (newest to oldest)
        for email_id in reversed(email_ids):
            logging.info(f"Found Netflix Email, ID: {email_id}")

            # Fetch the email data
            result, data = self._mail.fetch(email_id, '(RFC822)')
            raw_email = data[0][1]

            # Parse the raw email data
            parsed_email = email.message_from_bytes(raw_email)

            # Check if the email is from one of the specified senders
            is_from_netflix = False
            for m in SENDER_EMAILS:
                if m in parsed_email['From']:
                    is_from_netflix = True
                    break

            if is_from_netflix:
                # The Email should be a multipart mail, thus get the payload and parse for link
                html_payload = ""
                for f in parsed_email.get_payload():
                    if f.get_content_type() == "text/html":
                        html_payload = f.as_string()
                html_payload = html_payload.replace('=3D', '=').replace('&amp;', '&').replace('=\n', '')

                idx_start = -1
                for s in NETFLIX_LINK_START:
                    idx_start = html_payload.find(s)
                    if idx_start != -1:
                        break
                if idx_start == -1:
                    logging.error('Unable to parse the correct link in the Email. '
                                  'Maybe the search string is not correct anymore or the Email is not a update Email?')

                update_link = html_payload[idx_start:-1]
                idx_end = update_link.find('"')
                update_link = update_link[0:idx_end-1]
                # URL ist encoded with quote printable. Bring back the equal sign in the link
                update_link = update_link.replace('=3D', '=').replace('&amp;', '&').replace('=\n', '')
                if update_link != '':
                    update_link = 'https://' + update_link
                    ret = self.parse_html_for_button(update_link)
                    logging.info(f"Parsed Netflix Email. Successful: {ret}, Link: {update_link}")
                    if not ret:
                        AppriseNotifier().send_notification("Netflix", f"Something is wrong with the link try manually {update_link}")
                        #self._mail.store(email_id, '-FLAGS', r'(\Seen)')

            # Move Email into Netflix folder
            if self._move_to_mailbox:
                self._mail.copy(email_id, self._move_to_mailbox_name)
                self._mail.store(email_id, '+FLAGS', r'(\Deleted)')

        if self._move_to_mailbox:
            self._mail.expunge()


class NetflixScheduler:
    _polling_time: int
    _location_update: NetflixLocationUpdate

    def __init__(self, polling_time: int, location_update: NetflixLocationUpdate):
        self._polling_time = polling_time
        self._location_update = location_update

    def run(self):
        while True:
            try:
                self._location_update.fetch_mails()
                time.sleep(self._polling_time)
            except KeyboardInterrupt:
                logging.info("Break script by keyboard interrupt")
                break
            except Exception as e:
                logging.error(e)

        self._location_update.close()


if __name__ == '__main__':
    netflix_updater = NetflixLocationUpdate()
    scheduler = NetflixScheduler(polling_time=int(os.getenv("MAILBOX_POLLING_SECONDS")), location_update=netflix_updater)
    scheduler.run()
