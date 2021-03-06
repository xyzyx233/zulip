from django.conf import settings
from django.http import HttpRequest
from django.utils.translation import ugettext as _
from typing import Optional, Text

from zerver.lib.actions import check_send_stream_message, \
    check_send_private_message, send_rate_limited_pm_notification_to_bot_owner
from zerver.lib.exceptions import StreamDoesNotExistError, JsonableError, \
    ErrorCode
from zerver.lib.request import REQ, has_request_variables
from zerver.lib.send_email import FromAddress
from zerver.models import UserProfile, get_system_bot


MISSING_EVENT_HEADER_MESSAGE = """
Hi there!  Your bot {bot_name} just sent an HTTP request to {request_path} that
is missing the HTTP {header_name} header.  Because this header is how
{integration_name} indicates the event type, this usually indicates a configuration
issue, where you either entered the URL for a different integration, or are running
an older version of the third-party service that doesn't provide that header.
Contact {support_email} if you need help debugging!
"""

# Django prefixes all custom HTTP headers with `HTTP_`
DJANGO_HTTP_PREFIX = "HTTP_"

class MissingHTTPEventHeader(JsonableError):
    code = ErrorCode.MISSING_HTTP_EVENT_HEADER
    data_fields = ['header']

    def __init__(self, header: Text) -> None:
        self.header = header

    @staticmethod
    def msg_format() -> str:
        return _("Missing the HTTP event header '{header}'")

@has_request_variables
def check_send_webhook_message(
        request: HttpRequest, user_profile: UserProfile,
        topic: Text, body: Text, stream: Optional[Text]=REQ(default=None),
        user_specified_topic: Optional[Text]=REQ("topic", default=None)
) -> None:

    if stream is None:
        assert user_profile.bot_owner is not None
        check_send_private_message(user_profile, request.client,
                                   user_profile.bot_owner, body)
    else:
        if user_specified_topic is not None:
            topic = user_specified_topic

        try:
            check_send_stream_message(user_profile, request.client,
                                      stream, topic, body)
        except StreamDoesNotExistError:
            # A PM will be sent to the bot_owner by check_message, notifying
            # that the webhook bot just tried to send a message to a non-existent
            # stream, so we don't need to re-raise it since it clutters up
            # webhook-errors.log
            pass

def validate_extract_webhook_http_header(request: HttpRequest, header: Text,
                                         integration_name: Text) -> Text:
    extracted_header = request.META.get(DJANGO_HTTP_PREFIX + header)
    if extracted_header is None:
        message_body = MISSING_EVENT_HEADER_MESSAGE.format(
            bot_name=request.user.full_name,
            request_path=request.path,
            header_name=header,
            integration_name=integration_name,
            support_email=FromAddress.SUPPORT,
        )
        send_rate_limited_pm_notification_to_bot_owner(
            request.user, request.user.realm, message_body)

        raise MissingHTTPEventHeader(header)

    return extracted_header
