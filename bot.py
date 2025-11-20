import asyncio
import os
import random
from telethon import TelegramClient
# Import necessary types and functions for low-level API calls
from telethon.tl.types import Channel, InputChannel, ForumTopic, InputPeerChannel
from telethon.tl.functions.messages import CreateForumTopicRequest, GetForumTopicsRequest

# --- Configuration & Environment Setup ---
SESSION_NAME = 'topic_forwarder_session'
LAST_ID_FILE = 'last_forwarded_id.txt'
TOPIC_MAP = {1: 1} # General topic (ID 1) is always mapped to itself

# Global variables initialized to None
API_ID = None
API_HASH = None
SOURCE_GROUP = None
DESTINATION_GROUP = None
SKIP_TOPIC_IDS = []

def load_environment_variables():
    """
    Reads all configuration variables from the local '.env' file
    and critically converts the large group IDs to integers.
    """
    global API_ID, API_HASH, SOURCE_GROUP, DESTINATION_GROUP, SKIP_TOPIC_IDS

    env_vars = {}
    if not os.path.exists('.env'):
        return False

    print("Loading configuration from local .env file...")
    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip().replace('"', '').replace("'", '')

        raw_api_id = env_vars.get('TELEGRAM_API_ID')
        API_ID = int(raw_api_id) if raw_api_id else None
        API_HASH = env_vars.get('TELEGRAM_API_HASH')

        # --- CRITICAL: Convert Group IDs to Integers ---
        raw_source_group = env_vars.get('SOURCE_GROUP_ID')
        raw_dest_group = env_vars.get('DESTINATION_GROUP_ID')

        if raw_source_group:
            SOURCE_GROUP = int(raw_source_group)
        if raw_dest_group:
            DESTINATION_GROUP = int(raw_dest_group)

        # Handle SKIP_TOPIC_ID list
        skip_topics_str = env_vars.get('SKIP_TOPIC_ID', '')
        if skip_topics_str:
            SKIP_TOPIC_IDS = [int(i.strip()) for i in skip_topics_str.split(',') if i.strip().lstrip('-').isdigit()]

    except ValueError:
        print("Error: Group IDs or Topic IDs in .env must be valid integers.")
        return False
    except Exception as e:
        print(f"FATAL ERROR: Failed to read or parse the .env file: {e}")
        return False

    return all([API_ID, API_HASH, SOURCE_GROUP, DESTINATION_GROUP])

# --- Utility Functions for Tracking and API Compatibility ---

def load_last_id():
    """Loads the last successfully forwarded message ID and its topic context."""
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, 'r') as f:
            try:
                content = f.read().strip().split(':')
                if len(content) == 2:
                    return int(content[0]), int(content[1])
                return 0, 1
            except ValueError:
                return 0, 1
    return 0, 1

def save_last_id(message_id, topic_id):
    """Saves the last successfully forwarded message ID and its topic context."""
    with open(LAST_ID_FILE, 'w') as f:
        f.write(f"{message_id}:{topic_id}")

def get_destination_topic_id(source_topic_id):
    """Translates a source topic ID to the destination topic ID using the dynamic map."""
    return TOPIC_MAP.get(source_topic_id, 1)

async def fetch_all_topics(client, entity):
    """
    Fetches all forum topics from a supergroup/channel by scanning messages.
    Returns a list of topic dictionaries with id, title, and icon_emoji_id.
    """
    if not isinstance(entity, Channel):
        entity = await client.get_entity(entity)

    topics = {}  # Use dict to avoid duplicates
    seen_topic_ids = set()

    try:
        print(f"   Scanning messages to discover topics...")
        message_count = 0

        # Scan messages to find all unique topic IDs
        async for message in client.iter_messages(entity, limit=1000):
            message_count += 1

            # Check if this message belongs to a topic
            if hasattr(message, 'reply_to') and message.reply_to:
                topic_id = None

                # Get the topic ID from reply_to
                if hasattr(message.reply_to, 'reply_to_top_id') and message.reply_to.reply_to_top_id:
                    topic_id = message.reply_to.reply_to_top_id
                elif hasattr(message.reply_to, 'reply_to_msg_id'):
                    topic_id = message.reply_to.reply_to_msg_id

                if topic_id and topic_id not in seen_topic_ids:
                    seen_topic_ids.add(topic_id)

                    # Try to get the topic starter message
                    try:
                        topic_msg = await client.get_messages(entity, ids=topic_id)
                        icon_emoji_id = None

                        if topic_msg and not topic_msg.action:
                            title = topic_msg.message[:100] if topic_msg.message else f'Topic {topic_id}'
                        else:
                            # This is a service message that created the topic
                            if hasattr(topic_msg, 'action') and hasattr(topic_msg.action, 'title'):
                                title = topic_msg.action.title
                                # Extract icon emoji ID if available
                                if hasattr(topic_msg.action, 'icon_emoji_id'):
                                    icon_emoji_id = topic_msg.action.icon_emoji_id
                            else:
                                title = f'Topic {topic_id}'

                        topics[topic_id] = {
                            'id': topic_id,
                            'title': title,
                            'icon_emoji_id': icon_emoji_id
                        }
                        icon_info = f" (Icon: {icon_emoji_id})" if icon_emoji_id else ""
                        print(f"   Found topic {topic_id}: {title}{icon_info}")
                    except Exception as e:
                        print(f"   Could not fetch details for topic {topic_id}: {e}")
                        topics[topic_id] = {
                            'id': topic_id,
                            'title': f'Topic {topic_id}',
                            'icon_emoji_id': None
                        }

        print(f"   Scanned {message_count} messages, found {len(topics)} topics")

    except Exception as e:
        print(f"Error scanning messages for topics: {e}")

    # Always ensure General topic (ID 1) exists
    if 1 not in topics:
        topics[1] = {'id': 1, 'title': 'General', 'icon_emoji_id': None}

    # Convert dict to list and sort by ID
    return sorted(topics.values(), key=lambda t: t['id'])


async def ensure_destination_topics(client, source_entity, dest_entity):
    """
    Fetches ALL topics from the source, maps existing ones, and creates missing
    ones in the destination group, preserving the topic icon (emoji ID).
    Topics in SKIP_TOPIC_IDS are still created here.
    """
    print("--- 1. Ensuring Destination Topics Exist and Building Map (ALL Topics) ---")

    # 1. Get ALL Source Topics (Do NOT filter by SKIP_TOPIC_IDS here)
    all_source_topics = await fetch_all_topics(client, source_entity)
    # Exclude General topic (ID 1) from the mappable list
    mappable_source_topics = [t for t in all_source_topics if t['id'] != 1]
    source_topics_by_title = {t['title']: t['id'] for t in mappable_source_topics}

    if SKIP_TOPIC_IDS:
        print(f"   Note: Topics in {SKIP_TOPIC_IDS} will be created, but their content will be skipped.")

    # 2. Get Existing Destination Topics
    dest_topics = await fetch_all_topics(client, dest_entity)
    dest_topics_by_title = {t['title']: t['id'] for t in dest_topics if t['id'] != 1}

    # 3. Create/Map Topics

    # First, map existing topics by title
    for title, dest_id in dest_topics_by_title.items():
        if title in source_topics_by_title:
            source_id = source_topics_by_title[title]
            TOPIC_MAP[source_id] = dest_id
            print(f"   Mapped existing topic: Source {source_id} ('{title}') -> Dest {dest_id}")

    # Then, create any missing topics
    for topic in mappable_source_topics:
        source_id = topic['id']
        source_title = topic['title']

        if source_id not in TOPIC_MAP:
            # Check for and extract the icon emoji ID to preserve the icon
            icon_id = topic.get('icon_emoji_id', None)

            print(f"   Creating new topic in destination: '{source_title}' (Icon: {icon_id})...")

            try:
                # Convert entity to InputPeerChannel for the API call
                input_channel = InputPeerChannel(
                    channel_id=dest_entity.id,
                    access_hash=dest_entity.access_hash
                )

                # Use the proper CreateForumTopicRequest API to create the topic
                result = await client(CreateForumTopicRequest(
                    input_channel,
                    title=source_title,
                    icon_emoji_id=icon_id,
                    random_id=random.randint(-(2**63), 2**63 - 1)
                ))

                # Extract the newly created topic ID from the result
                # The result contains updates with the new topic message
                new_dest_id = None
                if hasattr(result, 'updates'):
                    for update in result.updates:
                        if hasattr(update, 'message') and hasattr(update.message, 'id'):
                            new_dest_id = update.message.id
                            break

                if new_dest_id:
                    TOPIC_MAP[source_id] = new_dest_id
                    print(f"   Created and Mapped: Source {source_id} ('{source_title}') -> Dest {new_dest_id}")
                else:
                    print(f"   ERROR: Could not extract topic ID from creation result! Skipping.")
            except Exception as e:
                 print(f"   FATAL TOPIC CREATION ERROR: Failed to create topic '{source_title}': {e}")

    print(f"--- Topic Map Completed: {TOPIC_MAP} ---")
    # Return all topics so the main loop can iterate over them all
    return all_source_topics


# --- Core Migration Logic ---

async def topic_migration_forwarder():
    """
    Connects to Telegram, maps topics, and forwards all subsequent messages.
    """
    # Load the last processed message ID and its topic context
    last_forwarded_id, last_forwarded_topic = load_last_id()

    # 1. Initialize Client and Connect
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

    try:
        source_entity = await client.get_entity(SOURCE_GROUP)
        dest_entity = await client.get_entity(DESTINATION_GROUP)

    except Exception as e:
        print(f"ERROR: Could not get entities using IDs '{SOURCE_GROUP}' or '{DESTINATION_GROUP}'. Ensure the IDs are correct and you are a member of both groups: {e}")
        await client.disconnect()
        return

    print(f"Connected. Last tracked ID: {last_forwarded_id} in Source Topic {last_forwarded_topic}")

    # 2. Map all topics (creating destination topics if necessary)
    source_topics = await ensure_destination_topics(client, source_entity, dest_entity)

    # 3. Determine starting point based on last session
    # We find the index of the topic we last processed to resume from there.
    start_index = next((i for i, t in enumerate(source_topics) if t['id'] == last_forwarded_topic), 0)
    topics_to_process = source_topics[start_index:]

    # 4. Iterate and Forward Messages
    for topic in topics_to_process:
        source_topic_id = topic['id']

        # Ensure the topic has been mapped (it should be, but as a safety)
        if source_topic_id not in TOPIC_MAP:
            print(f"   WARNING: Source Topic {source_topic_id} ('{topic['title']}') could not be mapped. Skipping.")
            continue

        dest_topic_id = get_destination_topic_id(source_topic_id)

        print(f"\n--- Processing Source Topic {source_topic_id} ('{topic['title']}') -> Dest Topic {dest_topic_id} ---")

        # --- Check if this topic's content should be skipped ---
        if source_topic_id in SKIP_TOPIC_IDS:
            print(f"      Topic ID {source_topic_id} is in SKIP_TOPIC_IDS. Content migration skipped.")

            # Find the highest message ID in this topic to mark it as fully processed.
            try:
                newest_message = await client.get_messages(
                    entity=source_entity,
                    reply_to=source_topic_id,
                    limit=1
                )
                if newest_message:
                    max_message_id = newest_message[0].id

                    # Update progress only if we are moving forward to ensure the skip is recorded
                    if source_topic_id > last_forwarded_topic or \
                       (source_topic_id == last_forwarded_topic and max_message_id > last_forwarded_id):

                        last_forwarded_id = max_message_id
                        last_forwarded_topic = source_topic_id
                        save_last_id(last_forwarded_id, last_forwarded_topic)
                        print(f"      Marked content up to ID {max_message_id} as processed (Skipped Topic).")

            except Exception as e:
                print(f"      Warning: Could not fetch max ID to mark skipped topic {source_topic_id} as complete: {e}")

            continue # Move immediately to the next topic
        # --- END SKIP CHECK ---

        # Set the starting point for iteration: only use the last ID if resuming *in the middle* of this specific topic.
        topic_min_id = last_forwarded_id if source_topic_id == last_forwarded_topic else 0

        # --- Using get_messages to fetch a batch of messages for the topic ---
        messages = await client.get_messages(
            entity=source_entity,
            min_id=topic_min_id,
            reply_to=source_topic_id,
            limit=5000
        )

        # get_messages returns messages newest first. Reverse the list to process chronologically.
        messages.reverse()

        # --- IMPROVED LOGGING ---
        if not messages:
            print(f"      No new messages found since ID {topic_min_id}. Moving to the next topic.")
            continue

        print(f"      Fetched {len(messages)} messages to process (starting from ID {topic_min_id + 1}).")
        # --- END IMPROVED LOGGING ---

        for message in messages:
            # Skip messages already processed if resuming mid-topic
            if message.id <= last_forwarded_id and source_topic_id == last_forwarded_topic:
                 continue

            # Skip the topic creation service message (always the first message with same ID as topic)
            if message.id == source_topic_id and hasattr(message, 'action'):
                continue

            # Skip service messages (user joins, etc.)
            if not message.text and not message.media:
                continue

            print(f"      Forwarding Message ID {message.id} (Topic {source_topic_id})...")

            try:
                await client.send_message(
                    entity=dest_entity,
                    message=message,
                    reply_to=dest_topic_id
                )

                # Update tracking file only after successful forward
                last_forwarded_id = message.id
                last_forwarded_topic = source_topic_id
                save_last_id(last_forwarded_id, last_forwarded_topic)

                # --- Mandatory sleep delay to avoid API rate limits (250ms) ---
                await asyncio.sleep(0.25)

            except Exception as e:
                print(f"         ! ERROR forwarding Message ID {message.id}: {e}. Saving progress and continuing...")
                # Save current progress - this message will be retried on next run
                save_last_id(last_forwarded_id, source_topic_id)
                # Break the inner loop (messages) and move to the next topic
                break

    print("\n--- Forwarding Complete ---")
    print(f"Final Last Forwarded ID saved: {last_forwarded_id} in Topic {last_forwarded_topic}")
    await client.log_out()


if __name__ == '__main__':
    if not load_environment_variables():
        print("\nFATAL ERROR: Mandatory configuration variables missing or invalid in the .env file.")
    else:
        print(f"Configuration Loaded. Source: {SOURCE_GROUP}, Destination: {DESTINATION_GROUP}, Skip Topics: {SKIP_TOPIC_IDS}")
        try:
            asyncio.run(topic_migration_forwarder())
        except KeyboardInterrupt:
            print("\nScript interrupted by user. Closing client.")
        except Exception as e:
            print(f"\nAn unhandled error occurred: {e}")
