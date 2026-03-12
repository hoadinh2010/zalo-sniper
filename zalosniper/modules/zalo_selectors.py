# All Playwright selectors isolated here.
# When Zalo Web updates its UI, only this file needs changing.

ZALO_WEB_URL = "https://chat.zalo.me"
LOGIN_INDICATOR = "input[data-id='txt_Main_Search']"       # search box — present when logged in

# Sidebar conversation list
GROUP_LIST_ITEM = ".conv-item"                              # each conversation item
GROUP_NAME_SELECTOR = ".conv-item-title__name .truncate"   # name text within conv-item

# Message area
MESSAGE_CONTAINER = "#messageViewScroll"                   # scroll container for messages
MESSAGE_ITEM = ".chat-item"                                # individual message (sent or received)
MESSAGE_SENDER = ".message-sender-name-content .truncate"  # sender name (received msgs only)
MESSAGE_CONTENT = "[data-component='text-container'] .text" # plain text content
MESSAGE_TIME = ".card-send-time__sendTime"                 # timestamp element
MESSAGE_FRAME = "[data-component='message-content-view']"  # wrapper holding data-qid
MESSAGE_ID_ATTR = "data-qid"                               # unique message ID attribute
MESSAGE_ME_CLASS = "me"                                    # class added to sent-by-me chat-items
