# All Playwright selectors isolated here.
# When Zalo Web updates its UI, only this file needs changing.

ZALO_WEB_URL = "https://chat.zalo.me"
LOGIN_INDICATOR = "input[placeholder='Tìm kiếm']"   # present when logged in
GROUP_LIST_ITEM = ".group-item"                       # each group in sidebar
GROUP_NAME = ".group-name"                            # group name text
MESSAGE_LIST = ".message-list"                        # message container
MESSAGE_ITEM = ".message-item"                        # individual message
MESSAGE_SENDER = ".sender-name"                       # sender display name
MESSAGE_CONTENT = ".message-content"                  # text content
MESSAGE_TIME = ".message-time"                        # time element
MESSAGE_ID_ATTR = "data-msg-id"                       # message unique ID attribute
