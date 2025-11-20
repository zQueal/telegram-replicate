# Telegram Topic Forwarder

A Python script that replicates forum topic structures between Telegram groups and forwards messages from a source group to a destination group.

## Features

- Automatically discovers and replicates all forum topics from source to destination group
- Preserves topic titles and emoji icons
- Forwards messages chronologically while maintaining topic organization
- Supports resumable operation with progress tracking (saves message ID and topic ID)
- Allows selective topic skipping (creates topics but doesn't forward content)
- Implements rate limiting to comply with Telegram API restrictions
- Robust error handling with detailed logging for troubleshooting
- Filters out non-topic messages during discovery to avoid false positives
- Validates topic creation actions to ensure only genuine forum topics are processed

## Requirements

- Python 3.7+
- Telethon library
- Active Telegram account with API credentials

## Installation

1. Install the required dependency:
```bash
pip install telethon
```

2. Create a `.env` file in the project directory with the following configuration:
```
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
SOURCE_GROUP_ID=source_group_id
DESTINATION_GROUP_ID=destination_group_id
SKIP_TOPIC_ID=topic_id1,topic_id2
```

### Configuration Variables

- `TELEGRAM_API_ID`: Your Telegram API ID (obtain from https://my.telegram.org)
- `TELEGRAM_API_HASH`: Your Telegram API hash
- `SOURCE_GROUP_ID`: The ID of the source Telegram group
- `DESTINATION_GROUP_ID`: The ID of the destination Telegram group
- `SKIP_TOPIC_ID` (optional): Comma-separated list of topic IDs to skip content forwarding

## Usage

Run the script:
```bash
python bot.py
```

On first run, you'll be prompted to authenticate with your Telegram account. The script will:
1. Load configuration from `.env` file
2. Connect to both source and destination groups
3. Scan source group messages to discover all forum topics (validates topic actions)
4. Map existing topics between source and destination by title
5. Create missing topics in the destination group with preserved icons
6. Forward messages from source to destination, organized by topic
7. Track progress in `last_forwarded_id.txt` (format: `message_id:topic_id`) for resumability

## How It Works

1. **Environment Loading**: Reads configuration from `.env` file with validation
2. **Topic Discovery**: Scans up to 1000 recent messages to identify forum topics by their action metadata
3. **Topic Validation**: Filters out non-topic messages and validates that discovered topics have proper forum topic actions
4. **Topic Mapping**: Maps source topics to destination topics by title, preserving the General topic (ID 1)
5. **Topic Creation**: Creates any missing topics in the destination group with preserved emoji icons
6. **Message Forwarding**: Forwards messages chronologically, organized by topic, skipping topic creation messages
7. **Progress Tracking**: Saves both message ID and topic ID to `last_forwarded_id.txt` for accurate resumption
8. **Rate Limiting**: Implements a 250ms delay between messages to avoid API restrictions
9. **Error Handling**: Comprehensive error handling with detailed logging for debugging

## Notes

- Topics listed in `SKIP_TOPIC_ID` will be created in the destination but their content won't be forwarded (progress is still tracked)
- The script can be safely interrupted and will resume from where it left off (both message ID and topic ID are saved)
- Requires membership in both source and destination groups
- The General topic (ID 1) is always included and mapped
- Topic discovery scans the most recent 1000 messages; for groups with many old topics, increase the limit in `fetch_all_topics()`
- Only messages with actual content (text or media) are forwarded; empty messages and topic creation actions are skipped
- The script validates that discovered topics are genuine forum topics by checking for action metadata
- Detailed console logging helps track progress and troubleshoot issues
- **Error Handling**: When a message fails to forward (e.g., protected content), the script logs the error, saves progress, and continues with the next message rather than stopping entirely

## Troubleshooting

### Protected Content Errors

If you encounter errors like:
```
! ERROR forwarding Message ID 535: You can't forward messages from a protected chat
```

**Cause**: The source group has content protection enabled, preventing message forwarding.

**Solution**:
1. Disable content protection in the source group settings (Group Settings → Chat History → Content Protection)
2. To retry failed messages, edit `last_forwarded_id.txt` and set the message ID to just before the first failure
3. Or delete `last_forwarded_id.txt` to restart from the beginning
4. Run the script again

### Resuming After Errors

The script saves progress after each successful message in `last_forwarded_id.txt` (format: `message_id:topic_id`). If messages were skipped due to errors:

1. Check the console output to identify which message IDs failed
2. Edit `last_forwarded_id.txt` to set the ID to just before the failed messages
3. Rerun the script to retry from that point
