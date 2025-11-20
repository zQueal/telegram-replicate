# Telegram Topic Forwarder

A Python script that replicates forum topic structures between Telegram groups and forwards messages from a source group to a destination group.

## Features

- Automatically discovers and replicates all forum topics from source to destination group
- Preserves topic titles and emoji icons
- Forwards messages chronologically while maintaining topic organization
- Supports resumable operation with progress tracking
- Allows selective topic skipping (creates topics but doesn't forward content)
- Implements rate limiting to comply with Telegram API restrictions

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
1. Connect to both source and destination groups
2. Scan and map all forum topics
3. Create missing topics in the destination group
4. Forward messages from source to destination, organized by topic
5. Track progress in `last_forwarded_id.txt` for resumability

## How It Works

1. **Topic Discovery**: Scans the source group messages to discover all forum topics
2. **Topic Mapping**: Maps source topics to destination topics by title
3. **Topic Creation**: Creates any missing topics in the destination group with preserved icons
4. **Message Forwarding**: Forwards messages chronologically, organized by topic
5. **Progress Tracking**: Saves the last processed message ID to allow resuming after interruptions
6. **Rate Limiting**: Implements a 250ms delay between messages to avoid API restrictions

## Notes

- Topics listed in `SKIP_TOPIC_ID` will be created in the destination but their content won't be forwarded
- The script can be safely interrupted and will resume from where it left off
- Requires membership in both source and destination groups
- The General topic (ID 1) is always included and mapped
